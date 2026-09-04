from __future__ import annotations

import re
import unittest
from pathlib import Path


class SkillHubPackageTests(unittest.TestCase):
    def test_skill_is_platform_neutral_and_preserves_skillhub_identity(self) -> None:
        root = Path(__file__).parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("name: wcl-report-data", skill)
        self.assertIn("slug: wcl-report-data", skill)
        self.assertNotIn("name: wcl-raid-coach", skill)
        self.assertNotIn("slug: wcl-raid-coach", skill)
        self.assertNotIn("WorkBuddy", skill)
        self.assertNotIn("/tmp", skill)
        self.assertNotRegex(skill, r"(?m)\\$")
        self.assertIn("<WORK_DIR>", skill)
        self.assertIn("references/setup.md", skill)

    def test_every_bundled_cli_example_enters_the_skill_root(self) -> None:
        root = Path(__file__).parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        bare_commands = re.findall(r"(?m)^python -m wcl_raid_coach(?:\s|$)", skill)

        self.assertEqual(bare_commands, [])
        self.assertIn('cd "<SKILL_ROOT>" && python -m wcl_raid_coach doctor', skill)

    def test_skill_routes_usage_help_requests(self) -> None:
        root = Path(__file__).parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = skill.split("---", 2)[1].lower()

        self.assertIn("如何使用", frontmatter)
        self.assertIn("how to use", frontmatter)

        usage_help = skill.split("### 使用帮助", 1)[1].split("## 2.", 1)[0]
        for workflow in ("报告数据", "机制复盘", "个人复盘", "通用攻略"):
            self.assertIn(workflow, usage_help)

    def test_runtime_document_links_resolve(self) -> None:
        root = Path(__file__).parents[1]
        runtime_documents = [root / "SKILL.md", root / "README.md", root / "README.en.md"]
        missing = []

        for document in runtime_documents:
            text = document.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
                if "://" in target or target.startswith("#"):
                    continue
                resolved = (document.parent / target.split("#", 1)[0]).resolve()
                if not resolved.exists():
                    missing.append(f"{document.name}: {target}")

        self.assertEqual(missing, [])

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
