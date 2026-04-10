#!/usr/bin/env python3
"""
AutoPCR Database Extractor

从 B站 AssetBundle 提取 SQLite 数据库并生成 manifest。
此脚本设计用于 GitHub Actions CI 环境运行。

Usage:
    python extract_db.py [--version VERSION] [--output-dir DIR]

Environment variables:
    DB_VERSION: 数据库版本号 (例如 "202604021043")
    BILI_ASSET_URL: B站 AssetBundle 地址 (可选，使用默认值)
"""

import os
import sys
import json
import hashlib
import argparse
import datetime
from pathlib import Path

try:
    import UnityPy
except ImportError:
    print("UnityPy not installed. Run: pip install UnityPy")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("requests not installed. Run: pip install requests")
    sys.exit(1)

BILI_ASSET_URL = "https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771/AssetBundles/Android/masterdata_master.unity3d"


def download_assetbundle(url: str) -> bytes:
    """从 B站服务器下载 AssetBundle。"""
    print(f"Downloading AssetBundle from {url}...")
    response = requests.get(url, timeout=600)
    response.raise_for_status()
    print(f"Downloaded {len(response.content)} bytes")
    return response.content


def extract_sqlite_from_assetbundle(raw: bytes) -> bytes:
    """使用 UnityPy 从 Unity AssetBundle 提取 SQLite 数据库。"""
    print("Loading AssetBundle with UnityPy...")
    env = UnityPy.load(raw)

    for obj in env.objects:
        if obj.type.name == "TextAsset":
            asset = obj.read()
            data = getattr(asset, "script", None)
            if data is None:
                data = getattr(asset, "m_Script", None)

            if data is not None:
                print(f"Found TextAsset: {asset.name}, data size: {len(data)} bytes")
                return bytes(data)

    raise ValueError("Could not find SQLite data in AssetBundle")


def generate_manifest(db_data: bytes, version: str) -> dict:
    """生成 manifest.json，包含校验和。"""
    checksum = hashlib.sha256(db_data).hexdigest()
    manifest = {
        "db_version": version,
        "schema_version": 3,
        "compatibility_version": 2,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "checksum_sha256": checksum,
        "size_bytes": len(db_data)
    }
    return manifest


def extract_db(version: str = None, output_dir: str = ".") -> dict:
    """
    主提取流程:
    1. 从 B站 下载 AssetBundle
    2. 使用 UnityPy 提取 SQLite
    3. 保存 .db 文件
    4. 生成 manifest.json
    """
    version = version or os.environ.get("DB_VERSION") or datetime.datetime.now().strftime("%Y%m%d%H%M")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    db_path = output_path / f"{version}.db"
    manifest_path = output_path / "manifest.json"

    print(f"Extracting database version {version}...")

    url = os.environ.get("BILI_ASSET_URL") or BILI_ASSET_URL
    raw = download_assetbundle(url)

    db_data = extract_sqlite_from_assetbundle(raw)

    with open(db_path, 'wb') as f:
        f.write(db_data)
    print(f"Saved database to {db_path}")

    manifest = generate_manifest(db_data, version)

    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"Saved manifest to {manifest_path}")

    print(f"\nExtraction complete!")
    print(f"  Version: {version}")
    print(f"  Size: {len(db_data)} bytes")
    print(f"  SHA256: {manifest['checksum_sha256']}")

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Extract database from Bilibili AssetBundle")
    parser.add_argument("--version", "-v", help="Database version (default: YYYYMMDDHHMM)")
    parser.add_argument("--output-dir", "-o", default=".", help="Output directory (default: current directory)")
    args = parser.parse_args()

    manifest = extract_db(args.version, args.output_dir)

    with open(Path(args.output_dir) / "manifest.json") as f:
        print(f"\nmanifest.json content:\n{f.read()}")


if __name__ == "__main__":
    main()
