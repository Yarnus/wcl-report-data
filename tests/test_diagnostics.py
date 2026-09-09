from __future__ import annotations

import gzip
import io
import json
import tempfile
import unittest
from http.client import IncompleteRead
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from tests.test_api import Response, isolated_schedule
from wcl_raid_coach import diagnostics
from wcl_raid_coach.__main__ import main
from wcl_raid_coach.api import WclClient
from wcl_raid_coach.config import Credentials
from wcl_raid_coach.errors import RateLimitError


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_schedule())

    def test_429_body_failure_still_trips_circuit_without_retry(self):
        for failure in (IncompleteRead(b"partial", 20), TimeoutError()):
            with self.subTest(failure=type(failure).__name__):
                client = WclClient(Credentials("id", "secret", "test"), max_retries=1, retry_backoff_seconds=0)
                body = io.BytesIO()
                error = HTTPError("https://example.invalid", 429, "limited", {}, body)
                with isolated_schedule(), diagnostics.collect() as metrics, patch.object(body, "read", side_effect=failure), patch("wcl_raid_coach.api.urlopen", side_effect=[error, Response(b"{}")]):
                    with self.assertRaises(RateLimitError):
                        client._request_json(Request("https://example.invalid"))
                    with self.assertRaises(RateLimitError):
                        client.fetch_report("ABC")
                self.assertEqual(metrics.snapshot()["network"]["OtherHTTP"]["attempts"], 1)

    def test_oversized_quota_integer_cannot_crash_diagnostics(self):
        with diagnostics.collect() as metrics:
            diagnostics.quota_snapshot({"limitPerHour": 10 ** 400, "pointsSpentThisHour": 0, "pointsResetIn": 1})
        self.assertEqual(metrics.snapshot()["quota"]["observations"], 0)

    def test_domain_failure_still_emits_diagnostics_without_error_content(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--diagnostics", "dataset", "remove", "secret-report"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())["ok"])
        self.assertEqual(json.loads(err.getvalue())["stages"]["command"]["calls"], 1)
        self.assertNotIn("secret-report", err.getvalue())

    def test_analysis_and_query_measure_real_validation_passes(self):
        from tests.test_analysis import AnalysisTests
        from wcl_raid_coach.analysis import analyze_player
        from wcl_raid_coach.dataset import query_bundle

        with tempfile.TemporaryDirectory() as directory:
            manifest, index = AnalysisTests().make_bundle(Path(directory))
            with diagnostics.collect() as metrics:
                result = analyze_player(manifest, index, 10, partition_id=2)
                query = query_bundle(manifest, limit=1)
            self.assertEqual(result["metrics"]["damage_total"], 150)
            self.assertEqual(query["matched"], 5)
            self.assertEqual(metrics.snapshot()["counters"]["canonical_event_passes"], 2)
            self.assertEqual(metrics.snapshot()["stages"]["bundle_input_validation"]["calls"], 2)

    def test_quota_observations_never_claim_attributable_cost_or_copy_extra_fields(self):
        client = WclClient(Credentials("id", "secret", "test"))
        with diagnostics.collect() as metrics:
            for spent in (100, 140, 5):
                client._update_rate_limit({
                    "limitPerHour": 3600, "pointsSpentThisHour": spent,
                    "pointsResetIn": 60, "secret": "private",
                })
        quota = metrics.snapshot()["quota"]
        self.assertEqual(quota["observations"], 3)
        self.assertEqual(quota["first"]["pointsSpentThisHour"], 100)
        self.assertEqual(quota["last"]["pointsSpentThisHour"], 5)
        self.assertIsNone(quota["attributable_cost"])
        self.assertNotIn("private", json.dumps(quota))

    def test_file_lock_wait_does_not_include_time_holding_lock(self):
        from wcl_raid_coach.dataset import _file_lock

        clock = [0.0]
        def wait(seconds):
            clock[0] += seconds

        with tempfile.TemporaryDirectory() as directory, diagnostics.collect() as metrics, patch(
            "wcl_raid_coach.dataset._try_file_lock", side_effect=[BlockingIOError, None]
        ), patch("wcl_raid_coach.diagnostics.monotonic", side_effect=lambda: clock[0]), patch(
            "wcl_raid_coach.dataset.time.sleep", side_effect=wait
        ):
            with _file_lock(Path(directory) / "lock", timeout_seconds=1, unavailable_message="busy"):
                clock[0] += 10
        self.assertAlmostEqual(metrics.snapshot()["stages"]["dataset_lock_wait"]["seconds"], 0.05)

    def test_network_counts_compressed_bytes_and_excludes_retry_wait(self):
        clock = [0.0]
        raw = gzip.compress(b'{"data":{"reportData":{"report":{"revision":3}}}}')
        responses = iter([
            Response(b'{"access_token":"private-token"}'),
            HTTPError("https://example.invalid", 503, "unavailable", {}, io.BytesIO(b"busy")),
            Response(raw, {"Content-Encoding": "gzip"}),
        ])

        def transport(*args, **kwargs):
            clock[0] += 2
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value

        def wait(seconds):
            clock[0] += seconds

        client = WclClient(Credentials("private-id", "private-secret", "test"), max_retries=1)
        with diagnostics.collect() as metrics, patch("wcl_raid_coach.api.urlopen", side_effect=transport), patch(
            "wcl_raid_coach.diagnostics.monotonic", side_effect=lambda: clock[0]
        ), patch("wcl_raid_coach.api.time.sleep", side_effect=wait):
            from wcl_raid_coach.api import REVISION_QUERY
            result = client.graphql(REVISION_QUERY, {"code": "private-report"})
        self.assertEqual(result["reportData"]["report"]["revision"], 3)
        report = metrics.snapshot()
        network = report["network"]["ReportRevision"]
        self.assertEqual(network["attempts"], 2)
        self.assertEqual(network["retries"], 1)
        self.assertEqual(network["response_body_bytes"], len(raw) + 4)
        self.assertEqual(network["seconds"], 4)
        self.assertEqual(report["network"]["OAuth"]["attempts"], 1)
        for secret in ("private-id", "private-secret", "private-token", "private-report", "reportData"):
            self.assertNotIn(secret, json.dumps(report))

    def test_nested_stages_record_exclusive_time_even_on_failure(self):
        clock = [0.0]
        with diagnostics.collect() as metrics, patch(
            "wcl_raid_coach.diagnostics.monotonic", side_effect=lambda: clock[0]
        ):
            with self.assertRaises(ValueError), diagnostics.stage("player_analysis"):
                clock[0] = 2
                with diagnostics.stage("complete_bundle_validation"):
                    clock[0] = 5
                clock[0] = 7
                raise ValueError("sensitive error")
        stages = metrics.snapshot()["stages"]
        self.assertEqual(stages["player_analysis"]["seconds"], 7)
        self.assertEqual(stages["player_analysis"]["exclusive_seconds"], 4)
        self.assertEqual(stages["complete_bundle_validation"]["seconds"], 3)

    def test_opt_in_stderr_preserves_json_stdout_and_resets_between_invocations(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["--data-root", directory, "--cache-root", directory, "dataset", "list"]
            for enabled in (True, False):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = main((["--diagnostics"] if enabled else []) + args)
                self.assertEqual(code, 0)
                self.assertTrue(json.loads(out.getvalue())["ok"])
                if enabled:
                    self.assertEqual(json.loads(err.getvalue())["kind"], "wcl_diagnostics")
                else:
                    self.assertEqual(err.getvalue(), "")
