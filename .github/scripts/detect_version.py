#!/usr/bin/env python3
"""
Auto-detect latest database version from Bilibili servers.
"""

import sys
import requests

BILI_ROOT = "https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771"
TIMEOUT = 30

FALLBACK_VERSIONS = ["202604021043", "202604011049", "202604001012"]


def try_version(version: str) -> bool:
    url = f"{BILI_ROOT}/Manifest/AssetBundles/Android/{version}/manifest/manifest_assetmanifest"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        return resp.status_code == 200
    except:
        return False


def detect_version() -> str:
    for version in FALLBACK_VERSIONS:
        if try_version(version):
            return version
    return ""


if __name__ == "__main__":
    version = detect_version()
    if version:
        print(version, flush=True)
        sys.exit(0)
    sys.exit(1)