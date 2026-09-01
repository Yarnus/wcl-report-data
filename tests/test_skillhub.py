from __future__ import annotations

import json
import unittest
from pathlib import Path


class SkillHubPackageTests(unittest.TestCase):
    def test_publishable_files_have_a_server_accepted_extension(self) -> None:
        root = Path(__file__).parents[1]
        excluded_directories = {".git", ".idea", ".vscode", "node_modules", "__pycache__"}
        excluded_files = {"AGENTS.md", "Makefile"}
        extensionless = []

        for path in root.rglob("*"):
            if not path.is_file() or any(part in excluded_directories for part in path.parts):
                continue
            if path.name in excluded_files:
                continue
            if not path.name.startswith(".") and not path.suffix:
                extensionless.append(path.relative_to(root).as_posix())

        self.assertEqual(extensionless, [])

    def test_zhcn_ability_mapping_has_matching_metadata(self) -> None:
        references = Path(__file__).parents[1] / "references"
        mapping = json.loads(
            (references / "ability-names.zhCN.json").read_text(encoding="utf-8")
        )
        metadata = json.loads(
            (references / "ability-names.zhCN.meta.json").read_text(encoding="utf-8")
        )

        self.assertTrue(all(key.isdigit() and int(key) > 0 for key in mapping))
        self.assertTrue(all(isinstance(name, str) and name for name in mapping.values()))
        self.assertEqual(metadata["locale"], "zhCN")
        self.assertEqual(metadata["ability_count"], len(mapping))


if __name__ == "__main__":
    unittest.main()
