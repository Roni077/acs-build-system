#!/usr/bin/env python3
"""
Mirror releases from a source repository (e.g. AndroidCSOfficial/acs-build-system)
to a destination repository (e.g. userio12/acs-build-system).

Usage:
    python scripts/mirror_releases.py [--source AndroidCSOfficial/acs-build-system] [--dest userio12/acs-build-system]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request


def run_cmd(cmd, check=True):
    """Run a system command and return stdout."""
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed ({' '.join(cmd)}):\n{res.stderr}")
    return res.stdout.strip(), res.returncode


def get_releases(repo):
    """Fetch all releases for a repository."""
    out, code = run_cmd(["gh", "api", f"repos/{repo}/releases", "--paginate"], check=False)
    if code != 0:
        return []
    return json.loads(out)


def get_dest_release(repo, tag):
    """Check if a release exists in dest repo."""
    out, code = run_cmd(["gh", "release", "view", tag, "-R", repo, "--json", "tagName,assets"], check=False)
    if code != 0:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def mirror_releases(source_repo, dest_repo):
    print(f"Fetching releases from source repository: {source_repo} ...")
    source_releases = get_releases(source_repo)

    if not source_releases:
        print(f"No releases found in {source_repo}.", file=sys.stderr)
        return

    print(f"Found {len(source_releases)} releases in {source_repo}.")

    # Reverse order so older releases are created first
    for rel in reversed(source_releases):
        tag = rel.get("tag_name")
        title = rel.get("name") or tag
        body = rel.get("body") or f"Release {tag} mirrored from {source_repo}"
        assets = rel.get("assets", [])

        print(f"\nProcessing release {tag} ({len(assets)} assets) ...")

        dest_rel = get_dest_release(dest_repo, tag)
        existing_asset_names = set()
        if dest_rel:
            existing_asset_names = {a.get("name") for a in dest_rel.get("assets", [])}

        missing_assets = [a for a in assets if a.get("name") not in existing_asset_names]

        if not missing_assets and dest_rel:
            print(f"  Release {tag} already complete with all assets in {dest_repo}.")
            continue

        temp_dir = tempfile.mkdtemp(prefix=f"mirror_{tag}_")
        downloaded_files = []

        try:
            for a in missing_assets:
                name = a.get("name")
                url = a.get("browser_download_url")
                dest_file = os.path.join(temp_dir, name)
                size_mb = a.get("size", 0) / (1024 * 1024)
                print(f"  Downloading {name} ({size_mb:.2f} MB) ...")
                urllib.request.urlretrieve(url, dest_file)
                downloaded_files.append(dest_file)

            if not dest_rel:
                print(f"  Creating release {tag} in {dest_repo} ...")
                cmd = ["gh", "release", "create", tag, *downloaded_files, "-t", title, "-n", body, "-R", dest_repo]
                run_cmd(cmd)
                print(f"  Successfully created release {tag} with {len(downloaded_files)} assets.")
            else:
                print(f"  Uploading {len(downloaded_files)} missing assets to existing release {tag} ...")
                cmd = ["gh", "release", "upload", tag, *downloaded_files, "-R", dest_repo]
                run_cmd(cmd)
                print(f"  Successfully uploaded assets to {tag}.")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    print("\nMirroring completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mirror GitHub releases between repositories.")
    parser.add_argument("--source", default="AndroidCSOfficial/acs-build-system", help="Source repository")
    parser.add_argument("--dest", default="userio12/acs-build-system", help="Destination repository")
    args = parser.parse_args()

    mirror_releases(args.source, args.dest)
