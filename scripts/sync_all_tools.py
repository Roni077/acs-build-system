#!/usr/bin/env python3
"""
Master Synchronizer for all ACS Build System Tools.
Orchestrates NDK, Build-Tools, Platform-Tools, CMake, and Flutter SDK synchronizers.
Regenerates acs-manifest.json and manifest.json upon completion.
"""

import argparse
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description="Orchestrate all ACS tool synchronizers.")
    parser.add_argument("--dest", default="Roni077/acs-build-system")
    parser.add_argument("--tools", choices=["all", "ndk", "build-tools", "cmake", "flutter"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dest = args.dest
    dry_run_flag = ["--dry-run"] if args.dry_run else []

    tools_to_run = ["ndk", "build-tools", "cmake", "flutter"] if args.tools == "all" else [args.tools]

    for tool in tools_to_run:
        print(f"\n{'='*60}\n  RUNNING SYNCHRONIZER: {tool.upper()}\n{'='*60}")
        if tool == "ndk":
            subprocess.run(["python", "scripts/sync_ndk.py", "--dest", dest, *dry_run_flag], check=True)
        elif tool == "build-tools":
            subprocess.run(["python", "scripts/sync_build_tools.py", "--dest", dest, *dry_run_flag], check=True)
        elif tool == "cmake":
            subprocess.run(["python", "scripts/sync_cmake.py", "--dest", dest, *dry_run_flag], check=True)
        elif tool == "flutter":
            subprocess.run(["python", "scripts/sync_flutter.py", "--dest", dest, *dry_run_flag], check=True)

    print(f"\n{'='*60}\n  REGENERATING MANIFESTS\n{'='*60}")
    subprocess.run(["python", "scripts/generate_manifest.py", "--repo", dest, "--output", "acs-manifest.json"], check=True)
    print("\nAll tool synchronizations and manifest regeneration completed successfully!")

if __name__ == "__main__":
    main()
