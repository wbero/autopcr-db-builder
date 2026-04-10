#!/usr/bin/env python3
"""
Auto-detect latest database version from Bilibili servers.
"""

import requests

BILI_MANIFEST_INDEX = "https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771/Manifest/AssetBundles/Android/"
TIMEOUT = 30


def detect_version() -> str:
    """
    Try to detect latest version by checking manifest index.
    Returns version string like '202604101230' or empty string if failed.
    """
    try:
        resp = requests.get(BILI_MANIFEST_INDEX, timeout=TIMEOUT)
        resp.raise_for_status()
        content = resp.text

        versions = []
        for line in content.split('\n'):
            if ',' in line:
                version = line.split(',')[0].strip()
                if version and version.isdigit() and len(version) >= 10:
                    versions.append(version)

        if versions:
            versions.sort(reverse=True)
            latest = versions[0]
            print(f"Detected latest version: {latest}")
            return latest

    except Exception as e:
        print(f"Failed to detect version: {e}")

    return ""


if __name__ == "__main__":
    version = detect_version()
    if version:
        print(version)
    else:
        print("ERROR: Could not detect version")
