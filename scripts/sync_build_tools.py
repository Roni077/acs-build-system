#!/usr/bin/env python3
"""
Dynamic Android SDK Build-Tools and Platform-Tools Synchronizer for ACS Build System.
Monitors upstream (HomuHomu833/android-sdk-custom), slices ARM build-tools and platform-tools,
creates GitHub releases in destination repository, and triggers manifest regeneration.
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

# ARM-only architecture configuration (x86_64 excluded)
ARCH_CONFIG = [
    {
        "homu_asset": "android-sdk-aarch64-linux-android.tar.xz",
        "arch_tag": "aarch64",
        "acs_arch": "arm64-v8a",
    },
    {
        "homu_asset": "android-sdk-armv7a-linux-androideabi.tar.xz",
        "arch_tag": "arm",
        "acs_arch": "armeabi-v7a",
    },
]

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

def compute_file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def slice_archive(tar_path, version, arch_tag, out_dir):
    """
    Extracts build-tools and platform-tools from HomuHomu SDK tarball
    and creates modular tar.xz archives:
      - build-tools-{version}-{arch_tag}.tar.xz
      - platform-tools-{version}-{arch_tag}.tar.xz
    """
    bt_filename = f"build-tools-{version}-{arch_tag}.tar.xz"
    pt_filename = f"platform-tools-{version}-{arch_tag}.tar.xz"
    bt_out_path = os.path.join(out_dir, bt_filename)
    pt_out_path = os.path.join(out_dir, pt_filename)

    bt_prefix_alt = "android-sdk/build-tools/"
    pt_prefix = "android-sdk/platform-tools"

    print(f"Opening {tar_path} for slicing...")
    with tarfile.open(tar_path, "r:xz") as src_tar:
        all_members = src_tar.getmembers()

        actual_bt_prefix = f"android-sdk/build-tools/{version}"
        for m in all_members:
            if m.name.startswith(bt_prefix_alt) and m.name != bt_prefix_alt:
                parts = m.name.split("/")
                if len(parts) >= 3:
                    actual_bt_prefix = f"android-sdk/build-tools/{parts[2]}"
                    break

        bt_members = []
        for m in all_members:
            if m.name.startswith(actual_bt_prefix):
                rel_path = m.name[len(actual_bt_prefix):]
                m.name = f"build-tools/{version}{rel_path}"
                bt_members.append(m)

        pt_members = []
        for m in all_members:
            if m.name.startswith(pt_prefix):
                rel_name = m.name[len("android-sdk/"):]
                m.name = rel_name
                pt_members.append(m)

        print(f"Found {len(bt_members)} build-tools members and {len(pt_members)} platform-tools members.")

        print(f"Creating {bt_out_path} ...")
        with tarfile.open(bt_out_path, "w:xz") as bt_tar:
            for m in bt_members:
                f = src_tar.extractfile(m) if m.isfile() else None
                bt_tar.addfile(m, f)

        print(f"Creating {pt_out_path} ...")
        with tarfile.open(pt_out_path, "w:xz") as pt_tar:
            for m in pt_members:
                f = src_tar.extractfile(m) if m.isfile() else None
                pt_tar.addfile(m, f)

    return bt_out_path, pt_out_path

def sync_build_tools(source_repo, dest_repo, target_version=None, target_arch="all", dry_run=False):
    print(f"Checking releases in upstream repository: {source_repo} ...")
    upstream_releases = get_repo_releases(source_repo)
    if not upstream_releases:
        print("No releases found in upstream repository.", file=sys.stderr)
        return False

    targets = ARCH_CONFIG
    if target_arch != "all":
        targets = [t for t in ARCH_CONFIG if t["arch_tag"] == target_arch]

    new_releases_processed = 0

    for rel in reversed(upstream_releases):
        version = rel.get("tag_name", "").lstrip("v")
        if target_version and version != target_version.lstrip("v"):
            continue

        # Skip legacy pre-35 versions unless explicitly requested
        if not target_version:
            try:
                major = int(version.split(".")[0])
                if major < 35:
                    continue
            except Exception:
                continue

        dest_tag = f"v{version}"
        dest_rel = get_dest_release(dest_repo, dest_tag)

        expected_asset_names = set()
        for t in targets:
            expected_asset_names.add(f"build-tools-{version}-{t['arch_tag']}.tar.xz")
            expected_asset_names.add(f"platform-tools-{version}-{t['arch_tag']}.tar.xz")

        if dest_rel:
            existing_asset_names = {a.get("name") for a in dest_rel.get("assets", [])}
            missing_names = expected_asset_names - existing_asset_names
            if not missing_names:
                print(f"Release {dest_tag} already up to date in {dest_repo}.")
                continue

        print(f"\nProcessing upstream Build-Tools release: {version}")
        if dry_run:
            print(f"  [Dry Run] Found upstream Build-Tools release {version} with targets: {[t['arch_tag'] for t in targets]}. Would slice and publish {list(expected_asset_names)}.")
            new_releases_processed += 1
            continue

        work_dir = os.path.join(tempfile.gettempdir(), f"sync_bt_{version}")
        os.makedirs(work_dir, exist_ok=True)
        generated_assets = []

        try:
            for target in targets:
                homu_asset = target["homu_asset"]
                arch_tag = target["arch_tag"]
                url = f"https://github.com/{source_repo}/releases/download/{version}/{homu_asset}"
                local_tar = os.path.join(work_dir, homu_asset)

                print(f"  Downloading {homu_asset} ...")
                subprocess.run(["curl", "-sL", "-o", local_tar, url], check=True)

                bt_path, pt_path = slice_archive(local_tar, version, arch_tag, work_dir)
                generated_assets.extend([bt_path, pt_path])

            if dry_run:
                print(f"  [Dry Run] Would publish {dest_tag} with {len(generated_assets)} files:")
                for a in generated_assets:
                    print(f"    - {os.path.basename(a)}")
                continue

            release_title = f"Android SDK Build-Tools {version}"
            body = (
                f"## Android SDK Build-Tools & Platform-Tools v{version}\n\n"
                f"- **Source**: [{source_repo}](https://github.com/{source_repo}/releases/tag/{version})\n"
                f"- **Architectures**: ARM (aarch64, arm)\n"
                f"- **Modular Slices**: Independent build-tools and platform-tools archives."
            )

            if dest_rel:
                missing_files = [f for f in generated_assets if os.path.basename(f) not in existing_asset_names]
                run_cmd(["gh", "release", "upload", dest_tag, *missing_files, "--clobber", "-R", dest_repo])
            else:
                run_cmd(["gh", "release", "create", dest_tag, *generated_assets, "-t", release_title, "-n", body, "-R", dest_repo])

            print(f"  Release {dest_tag} successfully published!")
            new_releases_processed += 1

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    print(f"\nBuild-Tools Sync completed. Total new/updated releases: {new_releases_processed}")
    return new_releases_processed > 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize Build-Tools releases to ACS.")
    parser.add_argument("--source", default="HomuHomu833/android-sdk-custom")
    parser.add_argument("--dest", default="Roni077/acs-build-system")
    parser.add_argument("--version", default=None)
    parser.add_argument("--arch", choices=["all", "aarch64", "arm"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sync_build_tools(args.source, args.dest, target_version=args.version, target_arch=args.arch, dry_run=args.dry_run)
