from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from tools import import_ability_names


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, filename: str) -> None:
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class ImportAbilityNamesTests(unittest.TestCase):
    def test_cli_entry_point_exposes_the_wago_importer(self) -> None:
        script = Path(__file__).parents[1] / "tools" / "import_ability_names.py"

        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Wago Tools", result.stdout)
        self.assertNotIn("--build", result.stdout)

    def test_downloads_wago_csv_and_preserves_its_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping_path = root / "ability-names.zhCN.json"
            mapping_path.write_text('{"188443": "旧名称"}\n', encoding="utf-8")
            metadata_path = root / "ability-names.zhCN.meta.json"
            index_path = root / "report.json"
            index_path.write_text(
                json.dumps({"abilities": [{"gameID": 7001}, {"gameID": 0}, {"gameID": True}]}),
                encoding="utf-8",
            )
            body = "ID,Name_lang\n188443,闪电链\n7001,沉重打击\n".encode()
            response = FakeResponse(
                body,
                "SpellName.12.1.0.69587.csv",
            )

            with patch.object(import_ability_names, "urlopen", return_value=response) as urlopen:
                result = import_ability_names.main(
                    [
                        "--report-index",
                        str(index_path),
                        "--mapping",
                        str(mapping_path),
                        "--metadata",
                        str(metadata_path),
                    ]
                )

            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(result, 0)
        self.assertEqual(urlopen.call_args.args[0].full_url, import_ability_names.WAGO_URL)
        self.assertEqual(mapping, {"7001": "沉重打击", "188443": "闪电链"})
        self.assertEqual(metadata["locale"], "zhCN")
        self.assertEqual(metadata["build"], "12.1.0.69587")
        self.assertEqual(metadata["source"], import_ability_names.WAGO_URL)
        self.assertEqual(metadata["source_file"], "SpellName.12.1.0.69587.csv")
        self.assertEqual(metadata["source_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(metadata["ability_count"], 2)

    def test_missing_existing_id_fails_without_changing_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping_path = root / "ability-names.zhCN.json"
            original = '{"188443": "闪电链"}\n'
            mapping_path.write_text(original, encoding="utf-8")
            response = FakeResponse(
                "ID,Name_lang\n7001,沉重打击\n".encode(),
                "SpellName.12.1.0.69587.csv",
            )

            with patch.object(import_ability_names, "urlopen", return_value=response):
                result = import_ability_names.main(
                    [
                        "--mapping",
                        str(mapping_path),
                        "--metadata",
                        str(root / "meta.json"),
                    ]
                )

            current = mapping_path.read_text(encoding="utf-8")

        self.assertEqual(result, 1)
        self.assertEqual(current, original)

    def test_rejects_a_response_without_a_build_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping_path = root / "ability-names.zhCN.json"
            mapping_path.write_text('{"188443": "闪电链"}\n', encoding="utf-8")
            response = FakeResponse(
                "ID,Name_lang\n188443,闪电链\n".encode(),
                "SpellName.csv",
            )

            with patch.object(import_ability_names, "urlopen", return_value=response):
                result = import_ability_names.main(
                    [
                        "--mapping",
                        str(mapping_path),
                        "--metadata",
                        str(root / "meta.json"),
                    ]
                )

            metadata_exists = (root / "meta.json").exists()

        self.assertEqual(result, 1)
        self.assertFalse(metadata_exists)


if __name__ == "__main__":
    unittest.main()
