from __future__ import annotations

import gzip
import io
import unittest
import tempfile
from contextlib import contextmanager
from pathlib import Path
from http.client import IncompleteRead
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from wcl_raid_coach.api import (
    FOCUSED_EVENT_QUERY,
    EVENT_QUERY,
    MECHANIC_EVENT_QUERY,
    RANKINGS_QUERY,
    REPORT_QUERY,
    REPORT_RESERVATION_POINTS,
    WclClient,
)
from wcl_raid_coach.config import Credentials
from wcl_raid_coach.api_schedule import ApiSchedule
from wcl_raid_coach.errors import ApiError, RateLimitError


class Response:
    def __init__(self, value: bytes | Exception, headers: dict[str, str] | None = None) -> None:
        self.value = value
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


@contextmanager
def isolated_schedule():
    with tempfile.TemporaryDirectory() as directory, patch("wcl_raid_coach.api_schedule.coordination_root", return_value=Path(directory)):
        with ApiSchedule().attempt("RateLimit") as scheduled:
            scheduled.observe({"data": {"rateLimitData": {
                "limitPerHour": 3600, "pointsSpentThisHour": 0, "pointsResetIn": 3600,
            }}})
        yield


class WclClientTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_schedule())

    def make_client(self, **kwargs) -> WclClient:
        return WclClient(Credentials("client-id", "client-secret", "test"), **kwargs)

    def test_candidate_metadata_reuse_still_checks_each_unique_identity(self):
        client = self.make_client()
        report = {"masterData": {"actors": [
            {"id": 10, "name": "Alpha", "server": "Realm", "subType": "Priest"},
            {"id": 11, "name": "Bravo", "server": "Realm", "subType": "Priest"},
        ]}, "fights": [{"id": 7, "friendlyPlayers": [10, 11], "friendlySpecs": ["Holy", "Shadow"]}]}
        candidate = {"report_code": "ABC", "fight_id": 7, "name": "Alpha", "server": "Realm", "class_name": "Priest", "spec_name": "Holy"}
        with patch.object(client, "graphql", return_value={"reportData": {"report": report}}) as graphql, patch.object(
            client, "rate_limit", return_value={"limitPerHour": 3600, "pointsSpentThisHour": 0, "pointsResetIn": 3600}
        ):
            self.assertEqual(client.resolve_candidate_source(candidate), 10)
            self.assertEqual(client.resolve_candidate_source(candidate | {"name": "Bravo", "spec_name": "Shadow"}), 11)
            self.assertIsNone(client.resolve_candidate_source(candidate | {"server": "Wrong"}))
            self.assertIsNone(client.resolve_candidate_source(candidate | {"spec_name": "Shadow"}))
        self.assertEqual(graphql.call_count, 1)

    def test_retries_incomplete_response(self) -> None:
        responses = [Response(IncompleteRead(b"", 1)), Response(b'{"ok": true}')]
        client = self.make_client(max_retries=1, retry_backoff_seconds=0)

        with patch("wcl_raid_coach.api.urlopen", side_effect=responses) as request, patch(
            "wcl_raid_coach.api.time.sleep"
        ) as sleep:
            result = client._request_json(Request("https://example.invalid"))

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0)

    def test_requests_and_decodes_gzip_responses(self) -> None:
        response = Response(gzip.compress(b'{"ok": true}'), {"Content-Encoding": "GZip"})
        request = Request("https://example.invalid")

        with patch("wcl_raid_coach.api.urlopen", return_value=response):
            result = self.make_client()._request_json(request)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.get_header("Accept-encoding"), "gzip")

    def test_rejects_an_invalid_gzip_response(self) -> None:
        response = Response(b"not gzip", {"Content-Encoding": "gzip"})

        with patch("wcl_raid_coach.api.urlopen", return_value=response):
            with self.assertRaisesRegex(ApiError, "invalid gzip"):
                self.make_client()._request_json(Request("https://example.invalid"))

    def test_rejects_a_gzip_response_with_an_invalid_deflate_stream(self) -> None:
        compressed = bytearray(gzip.compress(b'{"ok": true}'))
        compressed[10] = 0xFF
        response = Response(bytes(compressed), {"Content-Encoding": "gzip"})

        with patch("wcl_raid_coach.api.urlopen", return_value=response):
            with self.assertRaisesRegex(ApiError, "invalid gzip"):
                self.make_client()._request_json(Request("https://example.invalid"))

    def test_first_429_opens_circuit_breaker_without_retrying(self) -> None:
        error = HTTPError(
            "https://example.invalid",
            429,
            "limited",
            {},
            io.BytesIO(b'{"error":"limited"}'),
        )
        client = self.make_client(max_retries=2, retry_backoff_seconds=0)

        with patch("wcl_raid_coach.api.urlopen", side_effect=[error, error]) as request:
            with self.assertRaises(RateLimitError):
                client._request_json(Request("https://example.invalid"))

        self.assertEqual(request.call_count, 1)
        with self.assertRaises(RateLimitError):
            client.fetch_events_page("AbC123", 1, 1_000, 5_000)

    def test_event_query_refreshes_rate_limit_in_the_same_request(self) -> None:
        self.assertIn("rateLimitData", EVENT_QUERY)
        self.assertIn("dataType: All", EVENT_QUERY)
        self.assertIn("includeResources: true", EVENT_QUERY)
        self.assertIn("$endTime: Float", EVENT_QUERY)
        self.assertIn("endTime: $endTime", EVENT_QUERY)

    def test_mechanic_event_query_uses_server_side_filtering(self) -> None:
        self.assertIn("$filterExpression: String!", MECHANIC_EVENT_QUERY)
        self.assertIn("filterExpression: $filterExpression", MECHANIC_EVENT_QUERY)
        self.assertIn("targetID: $targetID", FOCUSED_EVENT_QUERY)
        self.assertNotIn("includeResources: true", MECHANIC_EVENT_QUERY)

    def test_report_index_uses_a_large_safety_reservation(self) -> None:
        self.assertGreaterEqual(REPORT_RESERVATION_POINTS, 500)

    def test_report_query_fetches_zone_encounter_order(self) -> None:
        self.assertIn("encounters { id name }", REPORT_QUERY)

    def test_report_query_fetches_ranking_partition_identity(self) -> None:
        self.assertIn("partitions { id name compactName default }", REPORT_QUERY)

    def test_rankings_query_uses_exact_raid_hard_conditions(self) -> None:
        for field in ("encounterID", "difficulty", "partition", "className", "specName"):
            self.assertIn(field, RANKINGS_QUERY)
        self.assertIn("externalBuffs: Exclude", RANKINGS_QUERY)

    def test_event_request_sends_the_fixed_fight_end_time(self) -> None:
        client = self.make_client()
        client._rate_limit_snapshot = {
            "limitPerHour": 3600,
            "pointsSpentThisHour": 0,
            "pointsResetIn": 3600,
        }
        response = {"rateLimitData": client._rate_limit_snapshot, "reportData": {"report": {"events": {"data": [], "nextPageTimestamp": None}}}}

        with patch.object(client, "graphql", return_value=response) as graphql:
            client.fetch_events_page("AbC123", 1, 2_000, 5_000)

        self.assertEqual(graphql.call_args.args[1]["startTime"], 2_000)
        self.assertEqual(graphql.call_args.args[1]["endTime"], 5_000)

    def test_mechanic_event_request_sends_filter_and_fixed_range(self) -> None:
        client = self.make_client()
        client._rate_limit_snapshot = {
            "limitPerHour": 3600,
            "pointsSpentThisHour": 0,
            "pointsResetIn": 3600,
        }
        response = {"rateLimitData": client._rate_limit_snapshot, "reportData": {"report": {"events": {"data": [], "nextPageTimestamp": None}}}}

        with patch.object(client, "graphql", return_value=response) as graphql:
            client.fetch_mechanic_events_page("AbC123", 1, 2_000, 5_000, "ability.id = 1")

        variables = graphql.call_args.args[1]
        self.assertEqual(variables["startTime"], 2_000)
        self.assertEqual(variables["endTime"], 5_000)
        self.assertEqual(variables["filterExpression"], "ability.id = 1")

    def test_focused_event_request_sends_target_and_fixed_range(self) -> None:
        client = self.make_client()
        client._rate_limit_snapshot = {
            "limitPerHour": 3600,
            "pointsSpentThisHour": 0,
            "pointsResetIn": 3600,
        }
        response = {"rateLimitData": client._rate_limit_snapshot, "reportData": {"report": {"events": {"data": [], "nextPageTimestamp": None}}}}

        with patch.object(client, "graphql", return_value=response) as graphql:
            client.fetch_focused_events_page("AbC123", 1, 2_000, 5_000, 10)

        query, variables = graphql.call_args.args
        self.assertEqual(query, FOCUSED_EVENT_QUERY)
        self.assertEqual(variables["startTime"], 2_000)
        self.assertEqual(variables["endTime"], 5_000)
        self.assertEqual(variables["targetID"], 10)
        self.assertNotIn("filterExpression", variables)

    def test_report_revision_rejects_a_boolean(self) -> None:
        client = self.make_client()
        client._rate_limit_snapshot = {
            "limitPerHour": 3600,
            "pointsSpentThisHour": 0,
            "pointsResetIn": 3600,
        }
        response = {"reportData": {"report": {"revision": True}}}

        with patch.object(client, "graphql", return_value=response):
            with self.assertRaises(ApiError):
                client.fetch_report_revision("AbC123")


if __name__ == "__main__":
    unittest.main()
