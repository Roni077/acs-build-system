#!/usr/bin/env python3
"""
Dynamic NDK Synchronizer for ACS Build System.
Monitors upstream (HomuHomu833/android-ndk-custom), fetches new ARM on-device Android NDK
releases (arm64-v8a, armeabi-v7a), inspects source.properties for canonical Pkg.Revision,
creates GitHub releases in destination repository, and regenerates manifests.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

# Target ARM architectures only (x86_64 removed)
ARCH_TARGETS = {
    "arm64-v8a": ("aarch64-linux-android.tar.xz", "aarch64"),
    "armeabi-v7a": ("armv7a-linux-androideabi.tar.xz", "arm"),
}

PRERELEASE_PATTERN = re.compile(r"[-_.](beta|rc)\d*", re.IGNORECASE)

def is_prerelease(text):
    return bool(PRERELEASE_PATTERN.search(text))

def run_cmd(cmd, check=True):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed ({' '.join(cmd)}):\n{res.stderr}")
    return res.stdout.strip(), res.returncode

def get_repo_releases(repo):
    out, code = run_cmd(["gh", "api", f"repos/{repo}/releases", "--paginate"], check=False)
    if code != 0:
        return []
    try:
        return json.loads(out)
    except Exception:
        return []

def get_dest_release(repo, tag):
    out, code = run_cmd(["gh", "release", "view", tag, "-R", repo, "--json", "tagName,assets"], check=False)
    if code != 0:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None

def extract_ndk_revision_from_tar(tar_path):
    """Read Pkg.Revision from source.properties inside the NDK tarball."""
    try:
        with tarfile.open(tar_path, "r:xz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("source.properties"):
                    f = tar.extractfile(member)
                    if f:
                        content = f.read().decode("utf-8", errors="ignore")
                        m = re.search(r"Pkg\.Revision\s*=\s*([0-9a-zA-Z\.\-]+)", content)
                        if m:
                            return m.group(1).strip()
    except Exception as e:
        print(f"Warning: could not inspect source.properties in {tar_path}: {e}", file=sys.stderr)
    return None

def sync_ndk(source_repo, dest_repo, target_tag=None, target_arch="all", dry_run=False):
    print(f"Checking releases in upstream repository: {source_repo} ...")
    upstream_releases = get_repo_releases(source_repo)
    if not upstream_releases:
        print("No releases found in upstream repository.", file=sys.stderr)
        return False

    dest_releases = get_repo_releases(dest_repo)
    new_releases_processed = 0

    selected_archs = ARCH_TARGETS
    if target_arch != "all" and target_arch in ARCH_TARGETS:
        selected_archs = {target_arch: ARCH_TARGETS[target_arch]}

    # Process oldest to newest so releases are ordered chronologically
    for rel in reversed(upstream_releases):
        tag = rel.get("tag_name", "")
        if target_tag and tag != target_tag:
            continue

        if not target_tag and is_prerelease(tag):
            continue

        assets = rel.get("assets", [])
        matched_assets = {}
        for arch, (asset_suffix, _) in selected_archs.items():
            for a in assets:
                name = a.get("name", "")
                if name.endswith(asset_suffix) and not is_prerelease(name):
                    matched_assets[arch] = a
                    break

        if not matched_assets:
            continue

        print(f"\nEvaluating upstream NDK release: {tag} ({len(matched_assets)} ARM architectures matched)")

        if dry_run:
            print(f"  [Dry Run] Found upstream NDK release {tag} with ARM assets: {[a.get('name') for a in matched_assets.values()]}. Would process and publish.")
            new_releases_processed += 1
            continue

        temp_dir = tempfile.mkdtemp(prefix=f"sync_ndk_{tag}_")
        downloaded_files = []
        canonical_revision = None

        try:
            for arch, asset in matched_assets.items():
                name = asset.get("name")
                url = asset.get("browser_download_url")
                dest_file = os.path.join(temp_dir, name)
                size_mb = asset.get("size", 0) / (1024 * 1024)
                print(f"  Downloading {name} ({size_mb:.2f} MB) ...")
                subprocess.run(["curl", "-sL", "-o", dest_file, url], check=True)
                downloaded_files.append(dest_file)

                if not canonical_revision:
                    canonical_revision = extract_ndk_revision_from_tar(dest_file)

            release_version = canonical_revision or tag.lstrip("r").lstrip("v")
            dest_tag = f"v{release_version}"

            dest_rel = get_dest_release(dest_repo, dest_tag)
            if dest_rel:
                existing_asset_names = {a.get("name") for a in dest_rel.get("assets", [])}
                missing_files = [f for f in downloaded_files if os.path.basename(f) not in existing_asset_names]
                if not missing_files:
                    print(f"  Release {dest_tag} already up to date in {dest_repo}.")
                    continue
                if not dry_run:
                    print(f"  Uploading {len(missing_files)} missing assets to existing release {dest_tag} ...")
                    run_cmd(["gh", "release", "upload", dest_tag, *missing_files, "-R", dest_repo])
                    new_releases_processed += 1
                else:
                    print(f"  [Dry Run] Would upload {len(missing_files)} missing assets to {dest_tag}")
            else:
                title = f"Android NDK {tag.upper()} ({release_version})"
                body = (
                    f"## Android NDK {tag.upper()}\n\n"
                    f"- **Version (Pkg.Revision)**: `{release_version}`\n"
                    f"- **Source**: [{source_repo}](https://github.com/{source_repo}/releases/tag/{tag})\n"
                    f"- **Supported Architectures**: {', '.join(matched_assets.keys())}\n"
                    f"- **Format**: Direct `.tar.xz` archives for on-device compilation."
                )
                print(f"  Creating new release {dest_tag} in {dest_repo} ...")
                if not dry_run:
                    run_cmd(["gh", "release", "create", dest_tag, *downloaded_files, "-t", title, "-n", body, "-R", dest_repo])
                    print(f"  Successfully published release {dest_tag}!")
                    new_releases_processed += 1
                else:
                    print(f"  [Dry Run] Would create release {dest_tag} with {len(downloaded_files)} files: {[os.path.basename(f) for f in downloaded_files]}")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"\nNDK Sync finished. Total new/updated releases: {new_releases_processed}")
    return new_releases_processed > 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize ARM NDK releases to ACS Build System.")
    parser.add_argument("--source", default="HomuHomu833/android-ndk-custom", help="Source repository")
    parser.add_argument("--dest", default="Roni077/acs-build-system", help="Destination repository")
    parser.add_argument("--tag", default=None, help="Specific upstream tag to sync (e.g. r30)")
    parser.add_argument("--arch", choices=["all", "arm64-v8a", "armeabi-v7a"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="Download and test without publishing")
    args = parser.parse_args()

    sync_ndk(args.source, args.dest, target_tag=args.tag, target_arch=args.arch, dry_run=args.dry_run)
