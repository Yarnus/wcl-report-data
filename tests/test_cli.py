from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from wcl_report_data.__main__ import create_parser, main


class CliTests(unittest.TestCase):
    def test_parser_accepts_explicit_env_file(self) -> None:
        args = create_parser().parse_args(["--env-file", "/actual/workspace/.env", "doctor"])

        self.assertEqual(args.env_file, Path("/actual/workspace/.env"))

    def test_prepare_parser_accepts_explicit_batch_selection(self) -> None:
        args = create_parser().parse_args(
            [
                "prepare",
                "https://www.warcraftlogs.com/reports/AbC123",
                "--fight",
                "1",
                "--fight",
                "2",
            ]
        )

        self.assertEqual(args.fight_ids, [1, 2])

    def test_dataset_list_is_structured_and_does_not_require_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "--data-root",
                        str(Path(temporary) / "data"),
                        "--cache-root",
                        str(Path(temporary) / "cache"),
                        "dataset",
                        "list",
                    ]
                )

        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reports"], [])

    def test_invalid_env_file_encoding_returns_a_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_bytes(b"WCL_CLIENT_ID=\xff\n")
            output = io.StringIO()

            with patch.dict("os.environ", {}, clear=True), redirect_stdout(output):
                status = main(["--env-file", str(env_file), "doctor"])

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "credentials_unavailable")


if __name__ == "__main__":
    unittest.main()
