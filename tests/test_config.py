from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from wcl_raid_coach.config import CredentialError, default_cache_root, default_data_root, resolve_credentials


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

    def test_reads_an_explicit_env_file_without_external_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "credentials.env"
            env_file.write_text(
                "export WCL_CLIENT_ID='file-id'\nWCL_CLIENT_SECRET=\"file-secret\"\n",
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

    def test_default_lookup_does_not_read_current_directory_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text(
                "WCL_CLIENT_ID=file-id\nWCL_CLIENT_SECRET=file-secret\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(temporary)
                with self.assertRaisesRegex(CredentialError, "--env-file"):
                    resolve_credentials(environ={})
            finally:
                os.chdir(previous)

    def test_persistent_workspace_is_the_compatible_default_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            data = default_data_root(environ={}, workspace=workspace)
            cache = default_cache_root(environ={}, workspace=workspace)

        self.assertEqual(data, workspace / "wcl-raid-coach")
        self.assertEqual(cache, workspace / ".cache" / "wcl-raid-coach")

    def test_user_directories_are_used_without_persistent_workspace(self) -> None:
        missing_workspace = Path("/path/that/does/not/exist")
        home = Path.home()

        data = default_data_root(environ={}, workspace=missing_workspace)
        cache = default_cache_root(environ={}, workspace=missing_workspace)

        self.assertEqual(data, home / ".local" / "share" / "wcl-raid-coach")
        self.assertEqual(cache, home / ".cache" / "wcl-raid-coach")

    def test_storage_environment_overrides_workspace_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            data = default_data_root(
                environ={"WCL_RAID_COACH_HOME": "~/custom-data"}, workspace=workspace
            )
            cache = default_cache_root(
                environ={"WCL_RAID_COACH_CACHE": "~/custom-cache"}, workspace=workspace
            )

        self.assertEqual(data, Path("~/custom-data").expanduser())
        self.assertEqual(cache, Path("~/custom-cache").expanduser())


if __name__ == "__main__":
    unittest.main()
