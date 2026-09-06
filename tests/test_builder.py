from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import detect_version


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


extract_db = load_script("extract_db", "extract_db.py")


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads: list[dict]):
        self.payloads = iter(payloads)
        self.headers: list[dict[str, str]] = []

    def post(self, _url, *, headers, data, timeout):
        self.headers.append(headers)
        self.data = json.loads(data)
        self.timeout = timeout
        return FakeResponse(next(self.payloads))


class VersionDetectionTest(unittest.TestCase):
    def test_reads_required_manifest_version(self):
        session = FakeSession(
            [{"data": {"manifest_ver": "1", "required_manifest_ver": "202609021434"}}]
        )

        result = detect_version.detect_version(session=session)

        self.assertEqual("202609021434", result)
        self.assertEqual({"viewer_id": None}, session.data)

    def test_retries_with_app_version_from_store_url(self):
        session = FakeSession(
            [
                {"data_headers": {"store_url": "https://example/gzlj_12.3.4/"}},
                {"data": {"manifest_ver": "202609031234"}},
            ]
        )

        result = detect_version.detect_version(app_version="1.0.0", session=session)

        self.assertEqual("202609031234", result)
        self.assertEqual(["1.0.0", "12.3.4"], [item["APP-VER"] for item in session.headers])


class ManifestParsingTest(unittest.TestCase):
    def test_parses_legacy_manifest_line(self):
        item = extract_db.AssetContent.from_line("a/test,abcdef,asset,123", "AssetBundles/Android")

        self.assertEqual("abcdef", item.md5)
        self.assertEqual("", item.checksum)
        self.assertEqual(123, item.size)

    def test_parses_extended_manifest_line(self):
        item = extract_db.AssetContent.from_line(
            "a/test,content-md5,pool-key,asset,456,extra", "AssetBundles/Android"
        )

        self.assertEqual("pool-key", item.md5)
        self.assertEqual("content-md5", item.checksum)
        self.assertEqual(456, item.size)


class DatabaseProcessingTest(unittest.TestCase):
    def test_unhashes_table_and_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "sample.db"
            rainbow = root / "rainbow.json"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    'CREATE TABLE "v1_table" ("v1_id" INTEGER PRIMARY KEY, "v1_name" TEXT)'
                )
                connection.execute('INSERT INTO "v1_table" VALUES (1, "Alice")')
                connection.commit()
            rainbow.write_text(
                json.dumps(
                    {
                        "v1_table": {
                            "--table_name": "unit_data",
                            "v1_id": "unit_id",
                            "v1_name": "unit_name",
                        }
                    }
                ),
                encoding="utf-8",
            )

            restored = extract_db.unhash_database(database, rainbow)

            self.assertEqual(1, restored)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    [(1, "Alice")],
                    connection.execute("SELECT unit_id, unit_name FROM unit_data").fetchall(),
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='v1_table'"
                    ).fetchone()
                )

    def test_validates_required_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sample.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "CREATE TABLE unit_data (unit_id INTEGER PRIMARY KEY, unit_name TEXT, "
                    "atk_type INTEGER, search_area_width INTEGER)"
                )
                connection.execute("INSERT INTO unit_data VALUES (1, 'Alice', 1, 100)")
                connection.execute("CREATE TABLE unit_skill_data (unit_id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO unit_skill_data VALUES (1)")
                connection.execute(
                    "CREATE TABLE skill_data (skill_id INTEGER PRIMARY KEY, description TEXT)"
                )
                connection.execute("INSERT INTO skill_data VALUES (1, 'skill')")
                connection.commit()

            counts = extract_db.validate_database(database)

            self.assertEqual(
                {"unit_data": 1, "unit_skill_data": 1, "skill_data": 1}, counts
            )


if __name__ == "__main__":
    unittest.main()
