#!/usr/bin/env python3
"""
AutoPCR Database Extractor

使用 UnityPy 从 B站 AssetBundle 提取 SQLite 数据库并生成 manifest。
此脚本设计用于 GitHub Actions CI 环境运行。

Usage:
    python extract_db.py [--version VERSION] [--output-dir DIR]

Environment variables:
    DB_VERSION: 数据库版本号 (例如 "202604021043")
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


BILI_ROOT = "https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771"
BILI_MANIFEST = f"{BILI_ROOT}/Manifest"
BILI_POOL = f"{BILI_ROOT}/pool"


def parse_manifest(content: str) -> dict:
    """解析 manifest 内容，返回 url -> (md5, size) 的映射"""
    registry = {}
    for line in content.strip().split('\n'):
        if not line or line.startswith('#'):
            continue
        parts = line.split(',')
        if len(parts) >= 4:
            url = parts[0].strip()
            md5 = parts[1].strip()
            size = int(parts[3].strip()) if parts[3].strip().isdigit() else 0
            registry[url] = (md5, size)
    return registry


def fetch_manifest(version: str) -> dict:
    """获取指定版本的 manifest"""
    manifest_url = f"{BILI_MANIFEST}/AssetBundles/Android/{version}/manifest/manifest_assetmanifest"
    print(f"Fetching manifest from: {manifest_url}")

    resp = requests.get(manifest_url, timeout=60)
    resp.raise_for_status()

    content = resp.text
    print(f"Manifest content length: {len(content)} bytes")
    print(f"First 500 chars: {content[:500]}")

    return parse_manifest(content)


def download_asset(url: str, registry: dict) -> bytes:
    """从 registry 下载资源"""
    if url not in registry:
        raise ValueError(f"URL not in registry: {url}")

    md5, size = registry[url]
    download_url = f"{BILI_POOL}/AssetBundles/Android/{md5[:2]}/{md5}"

    print(f"Downloading {url} from {download_url} ({size} bytes)")
    resp = requests.get(download_url, timeout=600)
    resp.raise_for_status()
    return resp.content


def extract_sqlite_from_assetbundle(raw: bytes) -> bytes:
    """使用 UnityPy 从 Unity AssetBundle 提取 SQLite 数据库。"""
    print(f"AssetBundle size: {len(raw)} bytes")
    print("Loading AssetBundle with UnityPy...")

    if hasattr(UnityPy, "config"):
        UnityPy.config.FALLBACK_UNITY_VERSION = "2021.3.20f1"

    try:
        from UnityPy.streams import EndianBinaryReader
        if hasattr(EndianBinaryReader, "align_stream") and not hasattr(EndianBinaryReader, "allign_stream"):
            EndianBinaryReader.allign_stream = EndianBinaryReader.align_stream
    except ImportError:
        pass

    env = UnityPy.load(raw)

    if not env.objects:
        raise RuntimeError("AssetBundle has no objects; may be incomplete or incompatible")

    print(f"AssetBundle contains {len(env.objects)} objects")

    for i, obj in enumerate(env.objects):
        if obj.type.name == "TextAsset":
            asset = obj.read()
            data = getattr(asset, "script", None)
            if data is None:
                data = getattr(asset, "m_Script", None)

            if data is not None:
                print(f"Found TextAsset at index {i}: {asset.name}")
                if isinstance(data, memoryview):
                    return data.tobytes()
                if isinstance(data, bytearray):
                    return bytes(data)
                if isinstance(data, bytes):
                    return data
                if isinstance(data, str):
                    return data.encode("utf-8", errors="surrogateescape")
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
    1. 获取 manifest
    2. 下载 masterdata_master.unity3d
    3. 使用 UnityPy 提取 SQLite
    4. 保存 .db 文件
    5. 生成 manifest.json
    """
    version = version or os.environ.get("DB_VERSION") or datetime.datetime.now().strftime("%Y%m%d%H%M")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    db_path = output_path / f"{version}.db"
    manifest_path = output_path / "manifest.json"

    print(f"Extracting database version {version}...")

    registry = fetch_manifest(version)
    print(f"Manifest contains {len(registry)} entries")

    print("Downloading masterdata_master.unity3d...")
    raw = download_asset('a/masterdata_master.unity3d', registry)
    print(f"Downloaded {len(raw)} bytes")

    db_data = extract_sqlite_from_assetbundle(raw)
    print(f"Extracted SQLite: {len(db_data)} bytes")

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
