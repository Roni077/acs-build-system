#!/usr/bin/env python3
"""
Dynamic CMake Synchronizer for ACS Build System.
Monitors HomuHomu833/cmake-custom for on-device Android CMake releases (ARM only),
creates GitHub releases in destination repository, and triggers manifest regeneration.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

CMAKE_ARCH_TARGETS = {
    "arm64-v8a": ("cmake-aarch64-linux-android.tar.xz", "aarch64"),
    "armeabi-v7a": ("cmake-armv7a-linux-androideabi.tar.xz", "arm"),
}

PRERELEASE_PAT = re.compile(r"[-_.](beta|rc)\d*", re.IGNORECASE)

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

def sync_cmake(source_repo, dest_repo, target_tag=None, target_arch="all", dry_run=False):
    print(f"Checking releases in upstream repository: {source_repo} ...")
    upstream_releases = get_repo_releases(source_repo)
    if not upstream_releases:
        print("No releases found upstream.", file=sys.stderr)
        return False

    selected_archs = CMAKE_ARCH_TARGETS
    if target_arch != "all" and target_arch in CMAKE_ARCH_TARGETS:
        selected_archs = {target_arch: CMAKE_ARCH_TARGETS[target_arch]}

    new_releases_processed = 0

    for rel in reversed(upstream_releases):
        tag = rel.get("tag_name", "")
        if target_tag and tag != target_tag:
            continue

        if not target_tag and bool(PRERELEASE_PAT.search(tag)):
            continue

        assets = rel.get("assets", [])
        matched_assets = {}
        for arch, (asset_name, _) in selected_archs.items():
            for a in assets:
                if a.get("name") == asset_name:
                    matched_assets[arch] = a
                    break

        if not matched_assets:
            continue

        version = tag.lstrip("v")
        dest_tag = f"v{version}"
        dest_rel = get_dest_release(dest_repo, dest_tag)

        if dest_rel:
            existing_asset_names = {a.get("name") for a in dest_rel.get("assets", [])}
            missing_assets = [a for a in matched_assets.values() if a.get("name") not in existing_asset_names]
            if not missing_assets:
                print(f"CMake release {dest_tag} already complete in {dest_repo}.")
                continue

        print(f"\nProcessing upstream CMake release: {tag} ({len(matched_assets)} ARM matched)")
        if dry_run:
            print(f"  [Dry Run] Found upstream CMake release {tag}. Would download and publish {list(matched_assets.keys())}.")
            new_releases_processed += 1
            continue

        temp_dir = tempfile.mkdtemp(prefix=f"sync_cmake_{version}_")
        downloaded_files = []

        try:
            for arch, asset in matched_assets.items():
                name = asset.get("name")
                url = asset.get("browser_download_url")
                dest_file = os.path.join(temp_dir, name)
                print(f"  Downloading {name} ...")
                subprocess.run(["curl", "-sL", "-o", dest_file, url], check=True)
                downloaded_files.append(dest_file)

            if dry_run:
                print(f"  [Dry Run] Would publish CMake release {dest_tag} with {len(downloaded_files)} files:")
                for f in downloaded_files:
                    print(f"    - {os.path.basename(f)}")
                continue

            title = f"Android CMake {version}"
            body = (
                f"## Android CMake {version}\n\n"
                f"- **Source**: [{source_repo}](https://github.com/{source_repo}/releases/tag/{tag})\n"
                f"- **Architectures**: {', '.join(matched_assets.keys())}\n"
                f"- **Format**: Prebuilt on-device Android binaries."
            )

            if dest_rel:
                missing_files = [f for f in downloaded_files if os.path.basename(f) not in existing_asset_names]
                run_cmd(["gh", "release", "upload", dest_tag, *missing_files, "--clobber", "-R", dest_repo])
            else:
                run_cmd(["gh", "release", "create", dest_tag, *downloaded_files, "-t", title, "-n", body, "-R", dest_repo])

            print(f"  Successfully published CMake release {dest_tag}!")
            new_releases_processed += 1

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"\nCMake Sync completed. Total new/updated releases: {new_releases_processed}")
    return new_releases_processed > 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize CMake releases to ACS.")
    parser.add_argument("--source", default="HomuHomu833/cmake-custom")
    parser.add_argument("--dest", default="Roni077/acs-build-system")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--arch", choices=["all", "arm64-v8a", "armeabi-v7a"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sync_cmake(args.source, args.dest, target_tag=args.tag, target_arch=args.arch, dry_run=args.dry_run)
