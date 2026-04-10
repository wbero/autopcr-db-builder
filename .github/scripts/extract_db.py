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

try:
    import pydantic
except ImportError:
    print("pydantic not installed. Run: pip install pydantic")
    sys.exit(1)


BILI_ROOT = "https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771"
BILI_MANIFEST = f"{BILI_ROOT}/Manifest"
BILI_POOL = f"{BILI_ROOT}/pool"


class AssetContent(pydantic.BaseModel):
    url: str = None
    md5: str = None
    type: str = None
    category: str = None
    size: int = 0
    children: list = None

    @property
    def is_assets(self) -> bool:
        return not self.url.startswith('manifest/')

    @staticmethod
    def from_line(line: str, category: str) -> "AssetContent":
        splits = line.split(',')
        offset = len(splits) > 5
        return AssetContent(
            url=splits[0],
            md5=splits[1],
            type=splits[2 + offset],
            size=int(splits[3 + offset]),
            category=category,
            children=[]
        )

    @staticmethod
    async def from_url(urlroot: str, url: str, category: str) -> list:
        text = await get_text(f'{urlroot}{url}')
        lines = text.split('\n')
        result = [AssetContent.from_line(line, category) for line in lines]
        for child in result:
            if not child.is_assets:
                child.children = await AssetContent.from_url(urlroot, child.url, child.category)
        return result

    async def download(self, urlgetter) -> bytes:
        content = urlgetter(self.md5)
        return await get_bytes(content)

    def resolve_url(self, md5: str) -> str:
        return f'{BILI_POOL}/{self.category}/{md5[:2]}/{md5}'


async def get_text(url: str) -> str:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.text


async def get_bytes(url: str) -> bytes:
    resp = requests.get(url, timeout=600)
    resp.raise_for_status()
    return resp.content


async def fetch_manifest(version: str) -> AssetContent:
    urlroot = f'{BILI_MANIFEST}/AssetBundles/Android/{version}/'
    return AssetContent(
        url='manifest/manifest_assetmanifest',
        type='every',
        category='AssetBundles/Android',
        children=await AssetContent.from_url(urlroot, 'manifest/manifest_assetmanifest', 'AssetBundles/Android')
    )


async def download_asset(url: str, registries: dict) -> bytes:
    content = registries[url]
    download_url = content.resolve_url(content.md5)
    return await get_bytes(download_url)


async def extract_sqlite_from_assetbundle(raw: bytes) -> bytes:
    """使用 UnityPy 从 Unity AssetBundle 提取 SQLite 数据库。"""
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

    for obj in env.objects:
        if obj.type.name == "TextAsset":
            asset = obj.read()
            data = getattr(asset, "script", None)
            if data is None:
                data = getattr(asset, "m_Script", None)

            if data is not None:
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


async def extract_db(version: str = None, output_dir: str = ".") -> dict:
    """
    主提取流程:
    1. 从 B站 获取 manifest
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

    print(f"Fetching manifest for version {version}...")
    manifest_root = await fetch_manifest(version)

    registries = {}
    def register_content(content: AssetContent):
        registries[content.url] = content
        if content.children:
            for child in content.children:
                register_content(child)

    for child in manifest_root.children:
        registries[child.url] = child

    print(f"Registered {len(registries)} assets")

    print("Downloading masterdata_master.unity3d...")
    raw = await download_asset('a/masterdata_master.unity3d', registries)
    print(f"Downloaded {len(raw)} bytes")

    db_data = await extract_sqlite_from_assetbundle(raw)
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

    import asyncio
    manifest = asyncio.run(extract_db(args.version, args.output_dir))

    with open(Path(args.output_dir) / "manifest.json") as f:
        print(f"\nmanifest.json content:\n{f.read()}")


if __name__ == "__main__":
    main()
