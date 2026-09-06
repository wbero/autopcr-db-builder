#!/usr/bin/env python3
"""Download, extract, unhash, validate, and package the AutoPCR database."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

try:
    import UnityPy
except ImportError as error:  # pragma: no cover - exercised by the workflow environment
    raise SystemExit("UnityPy not installed. Run: pip install UnityPy") from error


BILI_ROOT = "https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771"
BILI_MANIFEST = f"{BILI_ROOT}/Manifest"
BILI_POOL = f"{BILI_ROOT}/pool"
MASTERDATA_ASSET = "a/masterdata_master.unity3d"
DOWNLOAD_ATTEMPTS = 3
SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_SCHEMA = {
    "unit_data": {"unit_id", "unit_name", "atk_type", "search_area_width"},
    "unit_skill_data": {"unit_id"},
    "skill_data": {"skill_id", "description"},
}


@dataclass
class AssetContent:
    url: str
    md5: str = ""
    checksum: str = ""
    type: str = ""
    category: str = ""
    size: int = 0
    children: list["AssetContent"] = field(default_factory=list)

    @property
    def is_asset(self) -> bool:
        return not self.url.startswith("manifest/")

    @classmethod
    def from_line(cls, line: str, category: str) -> "AssetContent":
        fields = [value.strip() for value in line.strip().split(",")]
        if len(fields) < 4:
            raise ValueError(f"invalid manifest line: {line!r}")
        extended = len(fields) > 5
        size_index = 4 if extended else 3
        try:
            size = int(fields[size_index])
        except (IndexError, ValueError) as error:
            raise ValueError(f"invalid manifest size: {line!r}") from error
        return cls(
            url=fields[0],
            checksum=fields[1] if extended else "",
            md5=fields[2] if extended else fields[1],
            type=fields[3] if extended else fields[2],
            size=size,
            category=category,
        )

    def collect_into(self, registry: dict[str, "AssetContent"]) -> None:
        previous = registry.get(self.url)
        if previous and previous.checksum and not self.checksum:
            self.checksum = previous.checksum
        registry[self.url] = self
        for child in self.children:
            child.collect_into(registry)


class Downloader:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def bytes(
        self,
        url: str,
        *,
        timeout: int,
        expected_size: int = 0,
        expected_md5: str = "",
    ) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            try:
                response = self.session.get(url, timeout=timeout)
                response.raise_for_status()
                data = response.content
                if expected_size and len(data) != expected_size:
                    raise ValueError(
                        f"size mismatch: expected {expected_size}, received {len(data)}"
                    )
                if expected_md5:
                    actual = hashlib.md5(data).hexdigest()
                    if actual.lower() != expected_md5.lower():
                        raise ValueError(
                            f"MD5 mismatch: expected {expected_md5}, received {actual}"
                        )
                return data
            except Exception as error:
                last_error = error
                print(f"Download attempt {attempt}/{DOWNLOAD_ATTEMPTS} failed: {error}")
        raise RuntimeError(f"download failed after {DOWNLOAD_ATTEMPTS} attempts: {url}") from last_error


def _manifest_children(
    downloader: Downloader,
    root_url: str,
    relative_url: str,
    category: str,
    visited: set[str],
) -> list[AssetContent]:
    if relative_url in visited:
        return []
    visited.add(relative_url)
    raw = downloader.bytes(f"{root_url}{relative_url}", timeout=60)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise RuntimeError(f"manifest is not UTF-8: {relative_url}") from error
    result: list[AssetContent] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        item = AssetContent.from_line(line, category)
        if not item.is_asset:
            item.children = _manifest_children(
                downloader, root_url, item.url, item.category, visited
            )
        result.append(item)
    return result


def fetch_manifest(version: str, downloader: Downloader) -> dict[str, AssetContent]:
    root_url = f"{BILI_MANIFEST}/AssetBundles/Android/{version}/"
    root = AssetContent(
        url="manifest/manifest_assetmanifest",
        type="every",
        category="AssetBundles/Android",
        children=_manifest_children(
            downloader,
            root_url,
            "manifest/manifest_assetmanifest",
            "AssetBundles/Android",
            set(),
        ),
    )
    registry: dict[str, AssetContent] = {}
    root.collect_into(registry)
    if MASTERDATA_ASSET not in registry:
        raise RuntimeError(f"manifest {version} does not contain {MASTERDATA_ASSET}")
    print(f"Manifest {version} contains {len(registry)} entries")
    return registry


def download_asset(
    asset_url: str,
    registry: dict[str, AssetContent],
    downloader: Downloader,
) -> bytes:
    item = registry[asset_url]
    pool_url = f"{BILI_POOL}/{item.category}/{item.md5[:2]}/{item.md5}"
    print(f"Downloading {asset_url} ({item.size} bytes)")
    return downloader.bytes(
        pool_url,
        timeout=600,
        expected_size=item.size,
        expected_md5=item.checksum,
    )


def extract_sqlite_from_assetbundle(raw: bytes) -> bytes:
    UnityPy.config.FALLBACK_UNITY_VERSION = "2021.3.20f1"
    environment = UnityPy.load(raw)
    if not environment.objects:
        raise RuntimeError("AssetBundle has no objects")
    for item in environment.objects:
        if item.type.name != "TextAsset":
            continue
        asset = item.read()
        value = getattr(asset, "script", None)
        if value is None:
            value = getattr(asset, "m_Script", None)
        if isinstance(value, str):
            data = value.encode("utf-8", errors="surrogateescape")
        elif value is None:
            continue
        else:
            data = bytes(value)
        if data.startswith(SQLITE_HEADER):
            return data
    raise RuntimeError("AssetBundle does not contain a SQLite TextAsset")


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }


def unhash_database(database_path: Path, rainbow_path: Path) -> int:
    mapping = json.loads(rainbow_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        raise RuntimeError("rainbow mapping must be a JSON object")
    converted = 0
    with closing(sqlite3.connect(database_path)) as connection:
        for hashed_table, columns in mapping.items():
            if not isinstance(columns, dict):
                continue
            intact_table = columns.get("--table_name")
            if not intact_table or hashed_table not in _table_names(connection):
                continue
            create_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (hashed_table,),
            ).fetchone()
            if not create_row or not create_row[0]:
                continue
            create_sql = str(create_row[0]).replace(hashed_table, str(intact_table))
            hashed_columns: list[str] = []
            intact_columns: list[str] = []
            for hashed_column, intact_column in columns.items():
                if hashed_column == "--table_name":
                    continue
                hashed_columns.append(str(hashed_column))
                intact_columns.append(str(intact_column))
                create_sql = create_sql.replace(str(hashed_column), str(intact_column))
            existing_columns = [
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({_quote(hashed_table)})")
            ]
            for column in existing_columns:
                if column not in hashed_columns:
                    hashed_columns.append(column)
                    intact_columns.append(column)
            select_columns = ", ".join(_quote(value) for value in hashed_columns)
            insert_columns = ", ".join(_quote(value) for value in intact_columns)
            try:
                connection.execute("BEGIN")
                connection.execute(create_sql)
                connection.execute(
                    f"INSERT INTO {_quote(str(intact_table))} ({insert_columns}) "
                    f"SELECT {select_columns} FROM {_quote(hashed_table)}"
                )
                connection.execute(f"DROP TABLE {_quote(hashed_table)}")
                connection.commit()
                converted += 1
            except Exception:
                connection.rollback()
                raise
    print(f"Restored {converted} hashed tables")
    return converted


def validate_database(database_path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(database_path)) as connection:
        quick_check = connection.execute("PRAGMA quick_check(1)").fetchone()
        if not quick_check or str(quick_check[0]).lower() != "ok":
            raise RuntimeError(f"SQLite quick_check failed: {quick_check}")
        tables = _table_names(connection)
        for table, required_columns in REQUIRED_SCHEMA.items():
            if table not in tables:
                raise RuntimeError(f"required table is missing: {table}")
            actual_columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
            }
            missing = required_columns - actual_columns
            if missing:
                raise RuntimeError(
                    f"required columns are missing from {table}: {sorted(missing)}"
                )
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])
            for table in REQUIRED_SCHEMA
        }
        if counts["unit_data"] <= 0 or counts["skill_data"] <= 0:
            raise RuntimeError(f"required tables are empty: {counts}")
        return counts


def generate_manifest(
    database_path: Path,
    version: str,
    table_counts: dict[str, int],
    restored_tables: int,
) -> dict[str, Any]:
    data = database_path.read_bytes()
    return {
        "db_version": version,
        "schema_version": 4,
        "compatibility_version": 3,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "checksum_sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "restored_tables": restored_tables,
        "table_counts": table_counts,
    }


def extract_db(version: str, output_dir: Path, rainbow_path: Path) -> dict[str, Any]:
    if not version.isdigit() or len(version) != 12:
        raise ValueError(f"invalid database version: {version!r}")
    if not rainbow_path.is_file():
        raise FileNotFoundError(f"rainbow mapping not found: {rainbow_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    final_database = output_dir / f"{version}.db"
    final_manifest = output_dir / "manifest.json"
    downloader = Downloader()
    registry = fetch_manifest(version, downloader)
    bundle = download_asset(MASTERDATA_ASSET, registry, downloader)
    database = extract_sqlite_from_assetbundle(bundle)
    print(f"Extracted SQLite ({len(database)} bytes)")

    with tempfile.TemporaryDirectory(dir=output_dir) as temporary_dir:
        candidate = Path(temporary_dir) / f"{version}.candidate.db"
        candidate.write_bytes(database)
        restored_tables = unhash_database(candidate, rainbow_path)
        table_counts = validate_database(candidate)
        manifest = generate_manifest(candidate, version, table_counts, restored_tables)
        os.replace(candidate, final_database)
        temporary_manifest = Path(temporary_dir) / "manifest.json"
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_manifest, final_manifest)

    print(f"Database ready: {final_database}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="manifest version (YYYYMMDDHHMM)")
    parser.add_argument("--output-dir", type=Path, default=Path("db"))
    parser.add_argument("--rainbow", type=Path, required=True)
    args = parser.parse_args()
    try:
        extract_db(args.version, args.output_dir, args.rainbow)
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
