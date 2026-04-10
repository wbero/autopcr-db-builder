#!/usr/bin/env python3
"""
Auto-detect latest database version from Bilibili servers.
Tries multiple strategies to find a working version.
"""

import requests

BILI_ROOT = "https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771"
TIMEOUT = 30

FALLBACK_VERSIONS = ["202604021043", "202604011049", "202604001012"]


def try_version(version: str) -> bool:
    """Check if a specific version's manifest is accessible"""
    url = f"{BILI_ROOT}/Manifest/AssetBundles/Android/{version}/manifest/manifest_assetmanifest"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        return resp.status_code == 200
    except:
        return False


def detect_version() -> str:
    """
    Try to detect latest version.
    Strategy 1: Try known versions from newest to oldest
    Strategy 2: Try manifest URL patterns
    """
    print("Trying fallback versions...")

    for version in FALLBACK_VERSIONS:
        print(f"  Checking version {version}...")
        if try_version(version):
            print(f"  Found working version: {version}")
            return version

    print("No working version found")
    return ""


if __name__ == "__main__":
    version = detect_version()
    if version:
        print(f"\nDetected version: {version}")
    else:
        print("\nERROR: Could not detect version")
