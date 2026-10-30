#!/usr/bin/env python3
"""
Dynamic Flutter SDK Synchronizer for ACS Build System.
Monitors GeneralKaos666/flutter-for-termux for new AArch64 Flutter releases,
publishes releases to destination repository, and triggers manifest regeneration.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

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

def sync_flutter(source_repo, dest_repo, target_tag=None, dry_run=False):
    print(f"Checking releases in upstream repository: {source_repo} ...")
    upstream_releases = get_repo_releases(source_repo)
    if not upstream_releases:
        print("No releases found upstream.", file=sys.stderr)
        return False

    new_releases_processed = 0

    for rel in reversed(upstream_releases):
        tag = rel.get("tag_name", "").lstrip("v")
        if target_tag and tag != target_tag.lstrip("v"):
            continue

        assets = rel.get("assets", [])
        deb_asset = None
        for a in assets:
            name = a.get("name", "")
            if name.endswith("_aarch64.deb") and "flutter" in name:
                deb_asset = a
                break

        if not deb_asset:
            continue

        dest_tag = f"flutter-v{tag}"
        dest_rel = get_dest_release(dest_repo, dest_tag)

        if dest_rel:
            existing_names = {a.get("name") for a in dest_rel.get("assets", [])}
            if deb_asset.get("name") in existing_names:
                print(f"Flutter release {dest_tag} already up to date in {dest_repo}.")
                continue

        print(f"\nProcessing upstream Flutter release: {tag} ({deb_asset.get('name')})")
        if dry_run:
            print(f"  [Dry Run] Found upstream Flutter release {tag} ({deb_asset.get('name')}). Would download and publish {dest_tag}.")
            new_releases_processed += 1
            continue

        temp_dir = tempfile.mkdtemp(prefix=f"sync_flutter_{tag}_")
        dest_deb = os.path.join(temp_dir, deb_asset.get("name"))

        try:
            print(f"  Downloading {deb_asset.get('name')} ...")
            subprocess.run(["curl", "-sL", "-o", dest_deb, deb_asset.get("browser_download_url")], check=True)

            title = f"Flutter SDK {tag} (AArch64)"
            body = (
                f"## Flutter SDK v{tag}\n\n"
                f"- **Source**: [{source_repo}](https://github.com/{source_repo}/releases/tag/{tag})\n"
                f"- **Architecture**: ARM64 (`arm64-v8a`)\n"
                f"- **Format**: Prebuilt `.deb` package optimized for Android Code Studio Termux."
            )

            if dest_rel:
                run_cmd(["gh", "release", "upload", dest_tag, dest_deb, "--clobber", "-R", dest_repo])
            else:
                run_cmd(["gh", "release", "create", dest_tag, dest_deb, "-t", title, "-n", body, "-R", dest_repo])

            print(f"  Successfully published Flutter release {dest_tag}!")
            new_releases_processed += 1

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"\nFlutter Sync completed. Total new/updated releases: {new_releases_processed}")
    return new_releases_processed > 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize Flutter SDK releases to ACS.")
    parser.add_argument("--source", default="GeneralKaos666/flutter-for-termux")
    parser.add_argument("--dest", default="Roni077/acs-build-system")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sync_flutter(args.source, args.dest, target_tag=args.tag, dry_run=args.dry_run)
