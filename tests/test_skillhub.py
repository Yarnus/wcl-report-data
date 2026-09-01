from __future__ import annotations

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

if __name__ == "__main__":
    unittest.main()
