#!/usr/bin/env python3
"""
Generate and update acs-manifest.json and manifest.json from GitHub Releases.

Usage:
    python scripts/generate_manifest.py [--repo userio12/acs-build-system] [--output acs-manifest.json]
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request


def run_gh_api(endpoint):
    """Run a gh api command and return parsed JSON."""
    try:
        res = subprocess.run(
            ["gh", "api", endpoint, "--paginate"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(res.stdout)
    except Exception as e:
        print(f"Error running gh api {endpoint}: {e}", file=sys.stderr)
        return []


def detect_architecture(filename):
    """Detect package architecture from filename, returning (acs_arch, ide_arch)."""
    fn = filename.lower()
    if "arm64" in fn or "aarch64" in fn:
        return "arm64-v8a", "aarch64"
    elif "arm32" in fn or "armeabi" in fn or "armv7" in fn or "-arm" in fn or "_arm" in fn:
        return "armeabi-v7a", "arm"
    elif "x64" in fn or "x86_64" in fn:
        return "x86_64", "x86_64"
    elif "x86" in fn or "i686" in fn:
        return "x86", "x86"
    return "arm64-v8a", "aarch64"


def detect_package_id(filename):
    """Detect package type and id from filename."""
    fn = filename.lower()
    if "cmake" in fn:
        return "android-cmake", "cmake"
    elif "build-tools" in fn or "buildtools" in fn:
        return "android-build-tools", "build_tools"
    elif "platform-tools" in fn:
        return "android-platform-tools", "platform_tools"
    elif "cmdline-tools" in fn:
        return "android-cmdline-tools", "cmdline_tools"
    elif "android-sdk" in fn:
        return "android-sdk-core", "android_sdk"
    elif "ndk" in fn or "native" in fn:
        return "android-native-kit", "ndk"
    return "android-native-kit", "ndk"


def detect_bundle_version(filename):
    """Extract bundle version if present (e.g. bundle-v1 -> 1, bundle-v2 -> 2)."""
    m = re.search(r"bundle-v(\d+)", filename, re.IGNORECASE)
    if m:
        return m.group(1)
    return "-1"


def get_existing_manifest(path):
    """Load existing manifest if present to preserve known checksums."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def compute_remote_sha256(url):
    """Download a remote file and compute its SHA-256 hash."""
    h = hashlib.sha256()
    print(f"Streaming and hashing: {url} ...")
    with urllib.request.urlopen(url) as resp:
        while chunk := resp.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest(repo, output_path):
    print(f"Fetching releases for repository: {repo} ...")
    releases = run_gh_api(f"repos/{repo}/releases")

    if not releases:
        print(f"No releases found for {repo}.", file=sys.stderr)
        return False

    existing_manifest = get_existing_manifest(output_path)
    existing_checksums = {}
    if existing_manifest and "packages" in existing_manifest:
        for pkg in existing_manifest["packages"]:
            key = (pkg.get("filename"), pkg.get("version"))
            if "sha256" in pkg:
                existing_checksums[key] = pkg["sha256"]

    packages = []
    ndk_versions = set()
    cmake_versions = set()
    build_tools_versions = set()
    platform_tools_versions = set()
    supported_archs = set()

    # Mappings for idesetup jq queries
    build_tools_map = {"aarch64": {}, "arm": {}, "x86_64": {}}
    platform_tools_map = {"aarch64": {}, "arm": {}, "x86_64": {}}
    android_sdk_url = ""
    cmdline_tools_url = ""

    for r in releases:
        tag_name = r.get("tag_name", "")
        # Strip leading 'v' for version extraction
        version = tag_name.lstrip("v")
        assets = r.get("assets", [])

        for asset in assets:
            filename = asset.get("name", "")
            download_url = asset.get("browser_download_url", "")
            pkg_id, build_type = detect_package_id(filename)
            acs_arch, ide_arch = detect_architecture(filename)
            bundle_ver = detect_bundle_version(filename)
            is_encrypted = "bundle" in filename.lower()

            if build_type == "ndk":
                ndk_versions.add(version)
            elif build_type == "cmake":
                cmake_versions.add(version)
            elif build_type == "build_tools":
                build_tools_versions.add(version)
                ver_key = f"_{version.replace('.', '_')}"
                if ide_arch in build_tools_map:
                    build_tools_map[ide_arch][ver_key] = download_url
                    if version == "35.0.2" and "_35_0_1" not in build_tools_map[ide_arch]:
                        build_tools_map[ide_arch]["_35_0_1"] = download_url
                    elif version == "34.0.5" and "_34_0_4" not in build_tools_map[ide_arch]:
                        build_tools_map[ide_arch]["_34_0_4"] = download_url
            elif build_type == "platform_tools":
                platform_tools_versions.add(version)
                ver_key = f"_{version.replace('.', '_')}"
                if ide_arch in platform_tools_map:
                    platform_tools_map[ide_arch][ver_key] = download_url
                    if version == "35.0.2" and "_35_0_1" not in platform_tools_map[ide_arch]:
                        platform_tools_map[ide_arch]["_35_0_1"] = download_url
                    elif version == "34.0.5" and "_34_0_4" not in platform_tools_map[ide_arch]:
                        platform_tools_map[ide_arch]["_34_0_4"] = download_url
            elif build_type == "android_sdk":
                if not android_sdk_url:
                    android_sdk_url = download_url
            elif build_type == "cmdline_tools":
                if not cmdline_tools_url:
                    cmdline_tools_url = download_url

            supported_archs.add(acs_arch)

            # Lookup cached checksum or compute
            key = (filename, version)
            sha256_hash = existing_checksums.get(key, "")
            if not sha256_hash:
                for (fn, ver), sha in existing_checksums.items():
                    if fn == filename and sha:
                        sha256_hash = sha
                        break
            if not sha256_hash and download_url:
                try:
                    sha256_hash = compute_remote_sha256(download_url)
                except Exception as e:
                    print(f"Warning: could not compute sha256 for {filename}: {e}", file=sys.stderr)

            packages.append({
                "id": pkg_id,
                "architecture": acs_arch,
                "filename": filename,
                "version": version,
                "bundle_version": bundle_ver,
                "url": download_url,
                "encrypted": is_encrypted,
                "sha256": sha256_hash,
                "build_type": build_type,
            })

    # Sort packages logically by id, version (desc), architecture
    packages.sort(key=lambda p: (p["id"], p["version"], p["architecture"]), reverse=True)

    org, repo_name = repo.split("/", 1) if "/" in repo else ("", repo)

    manifest = {
        "manifest_version": "2.0.0",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "organization": org,
        "repository": repo_name,
        "total_builds": len(packages),
        "ndk_versions": sorted(list(ndk_versions), reverse=True),
        "cmake_versions": sorted(list(cmake_versions), reverse=True),
        "build_tools_versions": sorted(list(build_tools_versions), reverse=True),
        "platform_tools_versions": sorted(list(platform_tools_versions), reverse=True),
        "supported_architectures": sorted(list(supported_archs)),

        # idesetup compatibility fields
        "android_sdk": android_sdk_url,
        "cmdline_tools": cmdline_tools_url,
        "build_tools": build_tools_map,
        "platform_tools": platform_tools_map,

        # in-app acsprovider packages array
        "packages": packages,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Also write manifest.json in the same directory for direct URL compatibility
    out_dir = os.path.dirname(os.path.abspath(output_path))
    manifest_json_path = os.path.join(out_dir, "manifest.json")
    if os.path.abspath(output_path) != manifest_json_path:
        with open(manifest_json_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    print(f"Manifest successfully generated at: {output_path} (and {manifest_json_path})")
    print(f"Total packages: {len(packages)}")
    print(f"NDK versions: {manifest['ndk_versions']}")
    print(f"CMake versions: {manifest['cmake_versions']}")
    print(f"Build-Tools versions: {manifest['build_tools_versions']}")
    print(f"Platform-Tools versions: {manifest['platform_tools_versions']}")
    print(f"Supported architectures: {manifest['supported_architectures']}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate acs-manifest.json and manifest.json from GitHub Releases.")
    parser.add_argument("--repo", default="userio12/acs-build-system", help="GitHub repository in owner/repo format")
    parser.add_argument("--output", default="acs-manifest.json", help="Path to write manifest file")
    args = parser.parse_args()

    generate_manifest(args.repo, args.output)
