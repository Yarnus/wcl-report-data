from __future__ import annotations

import gzip
import io
import unittest
from http.client import IncompleteRead
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from wcl_report_data.api import EVENT_QUERY, REPORT_QUERY, REPORT_RESERVATION_POINTS, WclClient
from wcl_report_data.config import Credentials
from wcl_report_data.errors import ApiError, RateLimitError


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


class WclClientTests(unittest.TestCase):
    def make_client(self, **kwargs) -> WclClient:
        return WclClient(Credentials("client-id", "client-secret", "test"), **kwargs)

    def test_retries_incomplete_response(self) -> None:
        responses = [Response(IncompleteRead(b"", 1)), Response(b'{"ok": true}')]
        client = self.make_client(max_retries=1, retry_backoff_seconds=0)

        with patch("wcl_report_data.api.urlopen", side_effect=responses) as request, patch(
            "wcl_report_data.api.time.sleep"
        ) as sleep:
            result = client._request_json(Request("https://example.invalid"))

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0)

    def test_requests_and_decodes_gzip_responses(self) -> None:
        response = Response(gzip.compress(b'{"ok": true}'), {"Content-Encoding": "GZip"})
        request = Request("https://example.invalid")

        with patch("wcl_report_data.api.urlopen", return_value=response):
            result = self.make_client()._request_json(request)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.get_header("Accept-encoding"), "gzip")

    def test_rejects_an_invalid_gzip_response(self) -> None:
        response = Response(b"not gzip", {"Content-Encoding": "gzip"})

        with patch("wcl_report_data.api.urlopen", return_value=response):
            with self.assertRaisesRegex(ApiError, "invalid gzip"):
                self.make_client()._request_json(Request("https://example.invalid"))

    def test_rejects_a_gzip_response_with_an_invalid_deflate_stream(self) -> None:
        compressed = bytearray(gzip.compress(b'{"ok": true}'))
        compressed[10] = 0xFF
        response = Response(bytes(compressed), {"Content-Encoding": "gzip"})

        with patch("wcl_report_data.api.urlopen", return_value=response):
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

        with patch("wcl_report_data.api.urlopen", side_effect=[error, error]) as request:
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

    def test_report_index_uses_a_large_safety_reservation(self) -> None:
        self.assertGreaterEqual(REPORT_RESERVATION_POINTS, 500)

    def test_report_query_fetches_zone_encounter_order(self) -> None:
        self.assertIn("encounters { id name }", REPORT_QUERY)

    def test_event_request_sends_the_fixed_fight_end_time(self) -> None:
        client = self.make_client()
        client._rate_limit_snapshot = {
            "limitPerHour": 3600,
            "pointsSpentThisHour": 0,
            "pointsResetIn": 3600,
        }
        response = {"reportData": {"report": {"events": {"data": [], "nextPageTimestamp": None}}}}

        with patch.object(client, "graphql", return_value=response) as graphql:
            client.fetch_events_page("AbC123", 1, 2_000, 5_000)

        self.assertEqual(graphql.call_args.args[1]["startTime"], 2_000)
        self.assertEqual(graphql.call_args.args[1]["endTime"], 5_000)


if __name__ == "__main__":
    unittest.main()
