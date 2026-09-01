from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "tools" / "import_ability_names.py"


class ImportAbilityNamesTests(unittest.TestCase):
    def test_imports_union_of_existing_and_report_ability_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            csv_path = root / "SpellName.csv"
            csv_path.write_text(
                "ID,Name_lang\n188443,闪电链\n7001,沉重打击\n",
                encoding="utf-8",
            )
            mapping_path = root / "ability-names.zhCN.json"
            mapping_path.write_text('{"188443": "旧名称"}\n', encoding="utf-8")
            metadata_path = root / "ability-names.zhCN.meta.json"
            index_path = root / "report.json"
            index_path.write_text(
                json.dumps({"abilities": [{"gameID": 7001}, {"gameID": 0}, {"gameID": True}]}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(csv_path),
                    "--report-index",
                    str(index_path),
                    "--build",
                    "12.0.7.68974",
                    "--mapping",
                    str(mapping_path),
                    "--metadata",
                    str(metadata_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(mapping, {"7001": "沉重打击", "188443": "闪电链"})
        self.assertEqual(metadata["locale"], "zhCN")
        self.assertEqual(metadata["build"], "12.0.7.68974")
        self.assertEqual(metadata["ability_count"], 2)
        self.assertEqual(json.loads(result.stdout)["renamed_ids"], [188443])

    def test_missing_existing_id_fails_without_changing_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            csv_path = root / "SpellName.csv"
            csv_path.write_text("ID,Name_lang\n7001,沉重打击\n", encoding="utf-8")
            mapping_path = root / "ability-names.zhCN.json"
            original = '{"188443": "闪电链"}\n'
            mapping_path.write_text(original, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(csv_path),
                    "--build",
                    "12.0.7.68974",
                    "--mapping",
                    str(mapping_path),
                    "--metadata",
                    str(root / "meta.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            current = mapping_path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertIn("missing 1 required IDs", result.stdout)
        self.assertEqual(current, original)


if __name__ == "__main__":
    unittest.main()
