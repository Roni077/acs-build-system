# Android Code Studio Build System Repository

This repository hosts, indexes, and distributes custom-compiled **Android NDK** (C/C++ toolchains) and **CMake** binaries designed for on-device compilation within **Android Code Studio** and mobile Termux environments.

---

## Table of Contents
1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Manifest Specification (`acs-manifest.json`)](#3-manifest-specification)
4. [Supported Toolchains & Architectures](#4-supported-toolchains--architectures)
5. [Automated Scripts](#5-automated-scripts)
6. [Adding New NDK or CMake Versions](#6-adding-new-ndk-or-cmake-versions)
7. [Client Integration in Android Code Studio](#7-client-integration-in-android-code-studio)

---

## 1. Overview

Building native C/C++ applications on Android devices requires specialized toolchains:
- Standard desktop NDKs and CMake binaries are compiled for desktop host systems (x86_64 Linux/macOS/Windows).
- Mobile IDEs like Android Code Studio require **on-device host toolchains** compiled with target headers and libraries (Bionic/musl) so that `clang`, `lld`, `ninja`, and `cmake` execute natively on ARM64 and ARMv7 Android hardware.

Toolchains hosted here are sourced from and based on community builds by [Homura](https://github.com/HomuHomu833) and [AndroidIDE](https://github.com/AndroidIDEOfficial).

---

## 2. Architecture

```
[ Upstream Sources ]
  - HomuHomu833/android-ndk-custom (r25..r30)
  - HomuHomu833/cmake-custom (3.18..4.1.2)
         │
         ▼
[ Roni077/acs-build-system ]
  - GitHub Releases (Tagged assets)
  - scripts/generate_manifest.py (SHA-256 calculation)
  - acs-manifest.json (Central Index)
         │
         ▼
[ Client Device / Android Code Studio ]
  - idesetup (ARM64 / ARMv7)
  - $HOME/android-sdk/ndk/<version>/
  - $PREFIX/bin/cmake
```

---

## 3. Manifest Specification

The central index is [`acs-manifest.json`](./acs-manifest.json). Client setup scripts query this manifest to find download URLs and verify SHA-256 checksums:

```json
{
  "manifest_version": "1.0",
  "generated_at": "2026-10-25T15:00:00Z",
  "organization": "Roni077",
  "repository": "acs-build-system",
  "total_builds": 13,
  "ndk_versions": ["29.0.14033849", "28.2.13676358", "27.3.13750724"],
  "cmake_versions": ["4.1.2", "4.1.1", "3.31.6"],
  "supported_architectures": ["arm64-v8a", "armeabi-v7a", "x86_64"],
  "packages": [
    {
      "id": "android-native-kit",
      "architecture": "arm64-v8a",
      "filename": "android-native-development-kit-arm64-bundle-v1",
      "version": "28.2.13676358",
      "bundle_version": "1",
      "url": "https://github.com/Roni077/acs-build-system/releases/download/v28.2.13676358/android-native-development-kit-arm64-bundle-v1",
      "encrypted": true,
      "sha256": "87a9315e9792ceba693bef2d8d4b20e0218cc7bb4821574bab525ff496b7e63b",
      "build_type": "ndk"
    }
  ]
}
```

---

## 4. Supported Toolchains & Architectures

### Architectures
- **`arm64-v8a`** (AArch64 - standard 64-bit Android devices)
- **`armeabi-v7a`** (ARMv7 32-bit)
- **`x86_64`** (64-bit Android emulators and Chromebooks)

### Available NDK Versions
- **NDK r29** (`29.0.14033849`)
- **NDK r28** (`28.2.13676358`)
- **NDK r27d** (`27.3.13750724`)

### Available CMake Versions
- **CMake 4.1.2**
- **CMake 4.1.1**
- **CMake 3.31.6**

### Available Build-Tools & Platform-Tools
- **Build-Tools 35.0.2 / 35.0.1** (Android 15)
- **Platform-Tools 35.0.2** (Android 15 adb with Termux non-root support)
- Additional versions (`34.0.5`, `36.0.1`, `37.0.0`) available on demand via `sync-homuhomu.yml`

---

## 5. Automated Scripts

### 1. `scripts/generate_manifest.py`
Scans all GitHub Releases in this repository, inspects each asset, calculates/verifies SHA-256 sums, and outputs dual-compatibility `acs-manifest.json` and `manifest.json`:
```bash
python scripts/generate_manifest.py --repo Roni077/acs-build-system --output acs-manifest.json
```

### 2. `scripts/import_homuhomu_sdk.py`
Imports, slices, and publishes Android SDK, Build-Tools, and Platform-Tools from [HomuHomu833/android-sdk-custom](https://github.com/HomuHomu833/android-sdk-custom):
```bash
python scripts/import_homuhomu_sdk.py --version 35.0.2 --dest-repo Roni077/acs-build-system
```

### 3. `scripts/mirror_releases.py`
Mirrors releases and binary assets from upstream repositories into your fork:
```bash
python scripts/mirror_releases.py --source AndroidCSOfficial/acs-build-system --dest Roni077/acs-build-system
```

---

## 6. Adding New NDK or CMake Versions

To add a new toolchain version (e.g. NDK r30 or CMake 4.2):

1. **Obtain or Build Toolchain**:
   Download pre-compiled binaries from [HomuHomu833/android-ndk-custom](https://github.com/HomuHomu833/android-ndk-custom/releases).
2. **Create GitHub Release**:
   ```bash
   gh release create v30.0.0 android-ndk-r30-aarch64.tar.xz -t "v30.0.0" -R Roni077/acs-build-system
   ```
3. **Automated Manifest Update**:
   The included GitHub Actions workflow (`.github/workflows/update-manifest.yml`) automatically triggers on new releases, adds the package to `acs-manifest.json`, and commits the changes back to `main`.

---

## 7. Client Integration in Android Code Studio

In your `android-code-studio` repository, configure the `idesetup` bootstrap script to query your build system:

```bash
NDK_MANIFEST_FILE_URL="https://raw.githubusercontent.com/Roni077/acs-build-system/main/acs-manifest.json"
```

Clients executing onboarding will automatically fetch packages directly from your repository with full integrity verification.
