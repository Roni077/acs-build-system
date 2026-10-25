#!/usr/bin/env python3
"""
Import, slice, and publish Android SDK components from HomuHomu833/android-sdk-custom.

Usage:
    python scripts/import_homuhomu_sdk.py --version 35.0.1 [--repo userio12/acs-build-system] [--dry-run]
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


HOMU_ARCH_CONFIG = [
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
    {
        "homu_asset": "android-sdk-x86_64-linux-android.tar.xz",
        "arch_tag": "x86_64",
        "acs_arch": "x86_64",
    },
]


def compute_file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def download_file(url, dest_path):
    print(f"Downloading {url} -> {dest_path} ...")
    curl_bin = shutil.which("curl") or "curl.exe"
    try:
        subprocess.run(
            [curl_bin, "-L", "-C", "-", "--retry", "3", "-o", dest_path, url],
            check=True,
        )
        return True
    except Exception:
        urllib.request.urlretrieve(url, dest_path)
        return True


def slice_archive(tar_path, version, arch_tag, out_dir):
    """
    Extracts build-tools and platform-tools from HomuHomu SDK tarball
    and creates modular tar.xz archives:
      - build-tools-{version}-{arch_tag}.tar.xz (root prefix: build-tools/{version}/...)
      - platform-tools-{version}-{arch_tag}.tar.xz (root prefix: platform-tools/...)
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

        # Find actual build-tools directory name
        actual_bt_prefix = f"android-sdk/build-tools/{version}"
        for m in all_members:
            if m.name.startswith(bt_prefix_alt) and m.name != bt_prefix_alt:
                parts = m.name.split("/")
                if len(parts) >= 3:
                    actual_bt_prefix = f"android-sdk/build-tools/{parts[2]}"
                    break

        print(f"Detected build-tools directory in archive: {actual_bt_prefix}")

        # Collect build-tools members and ensure root is build-tools/{version}/...
        bt_members = []
        for m in all_members:
            if m.name.startswith(actual_bt_prefix):
                rel_path = m.name[len(actual_bt_prefix):]
                # Normalize so path is always build-tools/{version}/<rel_path>
                new_name = f"build-tools/{version}{rel_path}"
                m.name = new_name
                bt_members.append(m)

        # Collect platform-tools members
        pt_members = []
        for m in all_members:
            if m.name.startswith(pt_prefix):
                rel_name = m.name[len("android-sdk/"):]
                m.name = rel_name
                pt_members.append(m)

        print(f"Found {len(bt_members)} build-tools members and {len(pt_members)} platform-tools members.")

        # Write build-tools archive
        print(f"Creating {bt_out_path} ...")
        with tarfile.open(bt_out_path, "w:xz") as bt_tar:
            for m in bt_members:
                f = src_tar.extractfile(m) if m.isfile() else None
                bt_tar.addfile(m, f)

        # Write platform-tools archive
        print(f"Creating {pt_out_path} ...")
        with tarfile.open(pt_out_path, "w:xz") as pt_tar:
            for m in pt_members:
                f = src_tar.extractfile(m) if m.isfile() else None
                pt_tar.addfile(m, f)

    return bt_out_path, pt_out_path


def main():
    parser = argparse.ArgumentParser(description="Import SDK & Build-Tools from HomuHomu833.")
    parser.add_argument("--version", default="35.0.2", help="HomuHomu release version (e.g. 35.0.2 or 35.0.1)")
    parser.add_argument("--source-repo", default="HomuHomu833/android-sdk-custom", help="Source repository")
    parser.add_argument("--dest-repo", default="userio12/acs-build-system", help="Destination repository")
    parser.add_argument("--dry-run", action="store_true", help="Slice without publishing GitHub release")
    parser.add_argument("--arch", choices=["all", "aarch64", "arm", "x86_64"], default="all", help="Target architecture")
    parser.add_argument("--keep-bundle", action="store_true", help="Also upload the full android-sdk bundle")
    args = parser.parse_args()

    version = args.version
    source_repo = args.source_repo
    dest_repo = args.dest_repo

    targets = HOMU_ARCH_CONFIG
    if args.arch != "all":
        targets = [t for t in HOMU_ARCH_CONFIG if t["arch_tag"] == args.arch]

    work_dir = os.path.join(tempfile.gettempdir(), f"homu-import-{version}")
    os.makedirs(work_dir, exist_ok=True)

    generated_assets = []

    for target in targets:
        homu_asset = target["homu_asset"]
        arch_tag = target["arch_tag"]
        download_url = f"https://github.com/{source_repo}/releases/download/{version}/{homu_asset}"
        local_archive = os.path.join(work_dir, homu_asset)

        print(f"\n--- Processing {arch_tag} ({homu_asset}) ---")
        if not os.path.exists(local_archive) or os.path.getsize(local_archive) == 0:
            download_file(download_url, local_archive)

        bt_path, pt_path = slice_archive(local_archive, version, arch_tag, work_dir)
        generated_assets.append(bt_path)
        generated_assets.append(pt_path)

        if args.keep_bundle:
            bundle_name = f"android-sdk-{version}-{arch_tag}.tar.xz"
            bundle_path = os.path.join(work_dir, bundle_name)
            if not os.path.exists(bundle_path):
                shutil.copyfile(local_archive, bundle_path)
            generated_assets.append(bundle_path)

    print("\n--- Generated Packages ---")
    for asset in generated_assets:
        size_mb = os.path.getsize(asset) / (1024 * 1024)
        sha256 = compute_file_sha256(asset)
        print(f"  {os.path.basename(asset)}: {size_mb:.2f} MB | SHA-256: {sha256}")

    if args.dry_run:
        print("\n[DRY RUN] Skipping release creation.")
        return

    tag_name = f"v{version}"
    release_title = f"Android SDK Build-Tools {version}"
    notes = (
        f"Autonomous Android SDK Build-Tools and Platform-Tools v{version} "
        f"cross-compiled for Bionic Android.\nSourced from https://github.com/{source_repo}."
    )

    print(f"\nPublishing release {tag_name} to {dest_repo} ...")
    check_cmd = subprocess.run(
        ["gh", "release", "view", tag_name, "--repo", dest_repo],
        capture_output=True,
    )
    if check_cmd.returncode == 0:
        print(f"Release {tag_name} already exists. Uploading assets...")
        for asset in generated_assets:
            subprocess.run(
                ["gh", "release", "upload", tag_name, asset, "--clobber", "--repo", dest_repo],
                check=True,
            )
    else:
        print(f"Creating new release {tag_name}...")
        cmd = [
            "gh", "release", "create", tag_name,
            *generated_assets,
            "--title", release_title,
            "--notes", notes,
            "--repo", dest_repo,
        ]
        subprocess.run(cmd, check=True)

    print(f"Release {tag_name} successfully published to {dest_repo}!")


if __name__ == "__main__":
    main()
