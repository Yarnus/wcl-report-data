from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RELEASE_TOOL = ROOT / "tools" / "release.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


class ReleaseToolTests(unittest.TestCase):
    def test_plan_uses_conventional_commits_and_current_synchronized_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_versions(root, "2.0.0")
            self._git(root, "init")
            self._git(root, "config", "user.name", "Test")
            self._git(root, "config", "user.email", "test@example.com")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "chore: baseline")
            self._git(root, "tag", "v2.0.0")
            (root / "change.txt").write_text("change", encoding="utf-8")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "feat: portable agent skill")

            plan = json.loads(self._run(root, "plan", "--base-ref", "v2.0.0"))

        self.assertTrue(plan["release"])
        self.assertEqual(plan["bump"], "minor")
        self.assertEqual(plan["current_version"], "2.0.0")
        self.assertEqual(plan["next_version"], "2.1.0")
        self.assertEqual(plan["tag"], "v2.1.0")
        self.assertIn("feat: portable agent skill", plan["changelog"])

    def test_plan_uses_patch_for_a_fix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_versions(root, "2.0.0")
            self._git(root, "init")
            self._git(root, "config", "user.name", "Test")
            self._git(root, "config", "user.email", "test@example.com")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "chore: baseline")
            self._git(root, "tag", "v2.0.0")
            (root / "change.txt").write_text("change", encoding="utf-8")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "fix: keep revision isolation")

            plan = json.loads(self._run(root, "plan", "--base-ref", "v2.0.0"))

        self.assertEqual(plan["bump"], "patch")
        self.assertEqual(plan["next_version"], "2.0.1")

    def test_breaking_change_has_priority_over_a_feature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_versions(root, "2.4.3")
            self._git(root, "init")
            self._git(root, "config", "user.name", "Test")
            self._git(root, "config", "user.email", "test@example.com")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "chore: baseline")
            self._git(root, "tag", "v2.4.3")
            (root / "change.txt").write_text("feature", encoding="utf-8")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "feat: add portable storage")
            (root / "change.txt").write_text("breaking", encoding="utf-8")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "fix!: remove implicit env lookup")

            plan = json.loads(self._run(root, "plan", "--base-ref", "v2.4.3"))

        self.assertEqual(plan["bump"], "major")
        self.assertEqual(plan["next_version"], "3.0.0")

    def test_plan_does_not_release_documentation_only_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_versions(root, "2.0.0")
            self._git(root, "init")
            self._git(root, "config", "user.name", "Test")
            self._git(root, "config", "user.email", "test@example.com")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "chore: baseline")
            self._git(root, "tag", "v2.0.0")
            (root / "README.md").write_text("docs", encoding="utf-8")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "docs: clarify setup")

            plan = json.loads(self._run(root, "plan", "--base-ref", "v2.0.0"))

        self.assertFalse(plan["release"])
        self.assertIsNone(plan["next_version"])

    def test_release_workflow_reuses_one_tagged_artifact_for_both_destinations(self) -> None:
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('make package REF="$TAG"', workflow)
        self.assertIn('gh release upload "$TAG" "$ARCHIVE" --clobber', workflow)
        self.assertIn('gh release create "$TAG" "$ARCHIVE" --verify-tag', workflow)
        self.assertGreaterEqual(workflow.count('publish "$ARCHIVE"'), 2)
        self.assertIn('--dry-run --json', workflow)
        self.assertIn('--token "$SKILLHUB_TOKEN"', workflow)
        self.assertNotIn("skillhub auth token", workflow)

    def test_apply_updates_all_public_version_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_versions(root, "2.0.0")

            self._run(root, "apply", "2.1.0")

            self.assertIn("version: 2.1.0", (root / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn('version = "2.1.0"', (root / "pyproject.toml").read_text(encoding="utf-8"))
            self.assertIn('__version__ = "2.1.0"', (root / "wcl_raid_coach" / "__init__.py").read_text(encoding="utf-8"))

    def _write_versions(self, root: Path, version: str) -> None:
        (root / "wcl_raid_coach").mkdir()
        (root / "SKILL.md").write_text(f"---\nversion: {version}\n---\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
        (root / "wcl_raid_coach" / "__init__.py").write_text(
            f'__version__ = "{version}"\n', encoding="utf-8"
        )

    def _run(self, root: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["python", str(RELEASE_TOOL), "--root", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout

    def _git(self, root: Path, *arguments: str) -> None:
        subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
