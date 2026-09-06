#!/usr/bin/env python3
"""Detect the current Bilibili Princess Connect manifest version."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any

import requests


MAINTENANCE_URL = (
    "https://l3-prod-all-gs-gzlj.bilibiligame.net/"
    "source_ini/get_maintenance_status?format=json"
)
DEFAULT_APP_VERSION = "11.7.2"
DEFAULT_TIMEOUT = 30
VERSION_PATTERN = re.compile(r"^\d{12}$")
STORE_VERSION_PATTERN = re.compile(r"gzlj_(\d+\.\d+\.\d+)")


def request_headers(app_version: str) -> dict[str, str]:
    """Return the minimum stable header set used by the Android client."""
    account = "autopcr"
    return {
        "Accept-Encoding": "gzip",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 5.1.1; PCRT00 Build/LMY48Z)",
        "X-Unity-Version": "2021.3.20f1c1",
        "APP-VER": app_version,
        "BATTLE-LOGIC-VERSION": "4",
        "BUNDLE-VER": "",
        "DEVICE": "2",
        "DEVICE-NAME": "OPPO PCRT00",
        "EXCEL-VER": "1.0.0",
        "GRAPHICS-DEVICE-NAME": "Adreno (TM) 640",
        "IP-ADDRESS": "10.0.2.15",
        "KEYCHAIN": "",
        "LOCALE": "CN",
        "PLATFORM-OS-VERSION": "Android OS 5.1.1 / API-22",
        "REGION-CODE": "",
        "RES-VER": "10002200",
        "SHORT-UDID": "0",
        "RES-KEY": "ab00a0a6dd915a052a2ef7fd649083e5",
        "PLATFORM": "2",
        "PLATFORM-ID": "2",
        "CHANNEL-ID": "1",
        "DEVICE-ID": hashlib.md5(account.encode("utf-8")).hexdigest(),
        "Content-Type": "application/json",
    }


def _response_json(response: requests.Response) -> dict[str, Any]:
    response.raise_for_status()
    try:
        payload = response.json()
    except requests.JSONDecodeError as error:
        raise RuntimeError("maintenance endpoint returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise RuntimeError("maintenance endpoint returned an unexpected payload")
    return payload


def _manifest_from_payload(payload: dict[str, Any]) -> str | None:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return None
    version = str(data.get("required_manifest_ver") or data.get("manifest_ver") or "")
    return version if VERSION_PATTERN.fullmatch(version) else None


def _required_app_version(payload: dict[str, Any]) -> str | None:
    headers = payload.get("data_headers") or {}
    if not isinstance(headers, dict):
        return None
    match = STORE_VERSION_PATTERN.search(str(headers.get("store_url") or ""))
    return match.group(1) if match else None


def detect_version(
    app_version: str = DEFAULT_APP_VERSION,
    session: requests.Session | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Fetch the live manifest version, retrying once after an app-version hint."""
    client = session or requests.Session()
    current_app_version = app_version
    for _ in range(2):
        response = client.post(
            MAINTENANCE_URL,
            headers=request_headers(current_app_version),
            data=json.dumps({"viewer_id": None}).encode("utf-8"),
            timeout=timeout,
        )
        payload = _response_json(response)
        manifest_version = _manifest_from_payload(payload)
        if manifest_version:
            return manifest_version
        required_app_version = _required_app_version(payload)
        if not required_app_version or required_app_version == current_app_version:
            break
        current_app_version = required_app_version
    raise RuntimeError("game endpoint did not provide a valid manifest version")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-version",
        default=os.environ.get("APP_VERSION", DEFAULT_APP_VERSION),
        help="client version used for the maintenance request",
    )
    args = parser.parse_args()
    try:
        print(detect_version(args.app_version), flush=True)
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
