from __future__ import annotations

import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from wcl_report_data import ability_names


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, filename: str) -> None:
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AbilityNamesTests(unittest.TestCase):
    def test_downloads_the_complete_mapping_when_local_json_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            response = FakeResponse(
                "ID,Name_lang\n181035,\n188443,闪电链\n7001,沉重打击\n".encode(),
                "SpellName.12.1.0.69587.csv",
            )

            with (
                patch.object(ability_names, "MIN_COMPLETE_ROWS", 1),
                patch.object(ability_names, "urlopen", return_value=response),
            ):
                result = ability_names.ensure_ability_names(root)

            mapping = json.loads(Path(result["mapping_path"]).read_text(encoding="utf-8"))
            metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))

        self.assertEqual(mapping, {"188443": "闪电链", "7001": "沉重打击"})
        self.assertEqual(result["build"], "12.1.0.69587")
        self.assertEqual(metadata["ability_count"], 2)
        self.assertEqual(metadata["build"], result["build"])

    def test_reuses_existing_mapping_without_network_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping_path = root / ability_names.MAPPING_NAME
            metadata_path = root / ability_names.METADATA_NAME
            mapping_path.write_text('{"188443":"闪电链"}\n', encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "locale": "zhCN",
                        "build": "12.1.0.69587",
                        "source": ability_names.WAGO_URL,
                        "source_file": "SpellName.12.1.0.69587.csv",
                        "source_sha256": "a" * 64,
                        "source_row_count": 1,
                        "mapping_sha256": ability_names._sha256(mapping_path),
                        "ability_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            opener = Mock(side_effect=AssertionError("network should not be used"))

            with (
                patch.object(ability_names, "MIN_COMPLETE_ROWS", 1),
                patch.object(ability_names, "urlopen", opener),
            ):
                result = ability_names.ensure_ability_names(root)

        self.assertEqual(result["mapping_path"], str(mapping_path))
        self.assertEqual(result["build"], "12.1.0.69587")
        opener.assert_not_called()

    def test_replaces_an_old_partial_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ability_names.MAPPING_NAME).write_text(
                '{"188443":"闪电链"}\n', encoding="utf-8"
            )
            (root / ability_names.METADATA_NAME).write_text(
                json.dumps(
                    {
                        "locale": "zhCN",
                        "build": "12.0.7.68974",
                        "source": "maintainer-provided seed",
                        "ability_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            response = FakeResponse(
                "ID,Name_lang\n188443,闪电链\n7001,沉重打击\n".encode(),
                "SpellName.12.1.0.69587.csv",
            )

            with (
                patch.object(ability_names, "MIN_COMPLETE_ROWS", 1),
                patch.object(ability_names, "urlopen", return_value=response) as opener,
            ):
                result = ability_names.ensure_ability_names(root)

        self.assertEqual(result["ability_count"], 2)
        opener.assert_called_once()


if __name__ == "__main__":
    unittest.main()
