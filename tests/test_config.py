from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wcl_report_data.config import CredentialError, default_cache_root, default_data_root, resolve_credentials


class CredentialTests(unittest.TestCase):
    def test_process_environment_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text(
                "WCL_CLIENT_ID=file-id\nWCL_CLIENT_SECRET=file-secret\n",
                encoding="utf-8",
            )

            credentials = resolve_credentials(
                environ={"WCL_CLIENT_ID": "env-id", "WCL_CLIENT_SECRET": "env-secret"},
                env_files=[env_file],
            )

        self.assertEqual(credentials.client_id, "env-id")
        self.assertEqual(credentials.client_secret, "env-secret")
        self.assertEqual(credentials.source, "environment:WCL_CLIENT_ID")

    def test_reads_workbuddy_env_without_external_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text(
                "# WorkBuddy credentials\nexport WCL_CLIENT_ID='file-id'\nWCL_CLIENT_SECRET=\"file-secret\"\n",
                encoding="utf-8",
            )

            credentials = resolve_credentials(environ={}, env_files=[env_file])

        self.assertEqual(credentials.client_id, "file-id")
        self.assertEqual(credentials.client_secret, "file-secret")
        self.assertEqual(credentials.source, str(env_file))

    def test_accepts_existing_wcl_coach_names_as_a_complete_pair(self) -> None:
        credentials = resolve_credentials(
            environ={"WCL_ID": "legacy-id", "WCL_SECRET": "legacy-secret"},
            env_files=[],
        )

        self.assertEqual(credentials.client_id, "legacy-id")
        self.assertEqual(credentials.source, "environment:WCL_ID")

    def test_rejects_incomplete_pair(self) -> None:
        with self.assertRaises(CredentialError):
            resolve_credentials(environ={"WCL_CLIENT_ID": "id-only"}, env_files=[])

    def test_rejects_an_env_file_that_is_not_utf_8(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_bytes(b"WCL_CLIENT_ID=\xff\n")

            with self.assertRaisesRegex(CredentialError, "valid UTF-8"):
                resolve_credentials(environ={}, env_files=[env_file])

    def test_missing_credentials_mentions_local_env_file(self) -> None:
        with self.assertRaisesRegex(CredentialError, "current working directory"):
            resolve_credentials(environ={}, env_files=[])

    def test_workbuddy_workspace_is_the_default_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            data = default_data_root(environ={}, workspace=workspace)
            cache = default_cache_root(environ={}, workspace=workspace)

        self.assertEqual(data, workspace / "wcl-report-data")
        self.assertEqual(cache, workspace / ".cache" / "wcl-report-data")


if __name__ == "__main__":
    unittest.main()
