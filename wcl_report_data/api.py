from __future__ import annotations

import base64
import gzip
import http.client
import json
import ssl
import threading
import time
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Credentials
from .errors import ApiError, RateLimitError


TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://www.warcraftlogs.com/api/v2/client"
RETRYABLE_HTTP_STATUSES = {500, 502, 503, 504}
ESTIMATED_POINTS_PER_REQUEST = 10.0
REPORT_RESERVATION_POINTS = 500.0


REPORT_QUERY = """
query ReportIndex($code: String!) {
  reportData {
    report(code: $code, allowUnlisted: true) {
      code title visibility revision startTime endTime
      archiveStatus { isArchived isAccessible }
      zone { id name frozen difficulties { id name sizes } }
      masterData(translate: true) {
        logVersion gameVersion lang
        actors { id gameID name server type subType petOwner icon }
        abilities { gameID name type icon }
      }
      fights(translate: true) {
        id encounterID name startTime endTime kill inProgress difficulty size averageItemLevel
        fightPercentage bossPercentage friendlyPlayers friendlySpecs friendlyItemLevels
        keystoneLevel
        lastPhase lastPhaseAsAbsoluteIndex lastPhaseIsIntermission
        phaseTransitions { id startTime }
      }
    }
  }
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}
"""


EVENT_QUERY = """
query FightEvents($code: String!, $fightIDs: [Int], $startTime: Float, $endTime: Float, $limit: Int!) {
  reportData {
    report(code: $code, allowUnlisted: true) {
      events(
        fightIDs: $fightIDs, dataType: All, startTime: $startTime, endTime: $endTime, limit: $limit,
        includeResources: true, translate: true, useAbilityIDs: true, useActorIDs: true
      ) { data nextPageTimestamp }
    }
  }
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}
"""


REVISION_QUERY = """
query ReportRevision($code: String!) {
  reportData { report(code: $code, allowUnlisted: true) { revision } }
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}
"""


RATE_LIMIT_QUERY = """
query RateLimit {
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}
"""


class WclClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        timeout: int = 45,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.credentials = credentials
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.request_reservation_points = ESTIMATED_POINTS_PER_REQUEST * (max_retries + 1)
        self._token: str | None = None
        self._token_expiry = 0.0
        self._token_lock = threading.Lock()
        self._rate_limit_lock = threading.Lock()
        self._rate_limit_snapshot: dict[str, Any] | None = None
        self._rate_limit_generation = 0
        self._reserved_points = 0.0
        self._estimated_spent_points = 0.0
        self._rate_limit_tripped = threading.Event()

    def token(self) -> str:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        with self._token_lock:
            if self._token and time.time() < self._token_expiry - 30:
                return self._token
            basic = base64.b64encode(
                f"{self.credentials.client_id}:{self.credentials.client_secret}".encode()
            ).decode()
            request = Request(
                TOKEN_URL,
                data=urlencode({"grant_type": "client_credentials"}).encode(),
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            )
            payload = self._request_json(request)
            token = payload.get("access_token")
            if not isinstance(token, str):
                raise ApiError("WCL token response did not contain an access_token.")
            try:
                expires_in = int(payload.get("expires_in", 3600))
            except (TypeError, ValueError) as exc:
                raise ApiError("WCL token response contained an invalid expires_in value.") from exc
            self._token = token
            self._token_expiry = time.time() + expires_in
            return token

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        request = Request(
            API_URL,
            data=body,
            headers={"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"},
            method="POST",
        )
        payload = self._request_json(request)
        if payload.get("errors"):
            messages = "; ".join(str(error.get("message", error)) for error in payload["errors"])
            raise ApiError(f"WCL GraphQL error: {messages}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ApiError("WCL GraphQL response did not contain a data object.")
        if isinstance(data.get("rateLimitData"), dict):
            self._update_rate_limit(data["rateLimitData"])
        return data

    def fetch_report(self, code: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        self._ensure_circuit()
        with self.reserve_api_points(required_points=REPORT_RESERVATION_POINTS):
            data = self.graphql(REPORT_QUERY, {"code": code})
        report_data = data.get("reportData")
        report = report_data.get("report") if isinstance(report_data, dict) else None
        if not isinstance(report, dict):
            raise ApiError("The report does not exist or is not accessible with client credentials.")
        rate_limit = data.get("rateLimitData")
        return report, rate_limit if isinstance(rate_limit, dict) else None

    def fetch_events_page(
        self,
        code: str,
        fight_id: int,
        start_time: float,
        end_time: float,
        limit: int = 10_000,
    ) -> dict[str, Any]:
        self._ensure_circuit()
        with self.reserve_api_points():
            data = self.graphql(
                EVENT_QUERY,
                {
                    "code": code,
                    "fightIDs": [fight_id],
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": limit,
                },
            )
        report_data = data.get("reportData")
        report = report_data.get("report") if isinstance(report_data, dict) else None
        if not isinstance(report, dict):
            raise ApiError("The WCL report became inaccessible while fetching events.")
        page = report.get("events")
        if not isinstance(page, dict):
            raise ApiError("WCL returned no event paginator.")
        return page

    def fetch_report_revision(self, code: str) -> int:
        self._ensure_circuit()
        with self.reserve_api_points():
            data = self.graphql(REVISION_QUERY, {"code": code})
        report_data = data.get("reportData")
        report = report_data.get("report") if isinstance(report_data, dict) else None
        revision = report.get("revision") if isinstance(report, dict) else None
        if not isinstance(revision, int):
            raise ApiError("WCL did not return a numeric report revision.")
        return revision

    def rate_limit(self) -> dict[str, Any]:
        self._ensure_circuit()
        data = self.graphql(RATE_LIMIT_QUERY)
        value = data.get("rateLimitData")
        if not isinstance(value, dict):
            raise ApiError("WCL did not return rate-limit data.")
        return dict(value)

    @contextmanager
    def reserve_api_points(
        self, reserve_fraction: float = 0.15, required_points: float | None = None
    ) -> Iterator[None]:
        required = self.request_reservation_points if required_points is None else required_points
        self._ensure_circuit()
        rate = self._latest_rate_limit()
        with self._rate_limit_lock:
            limit = float(rate["limitPerHour"])
            remaining = (
                limit
                - float(rate["pointsSpentThisHour"])
                - self._estimated_spent_points
                - self._reserved_points
            )
            if remaining - required < max(50.0, limit * reserve_fraction):
                raise RateLimitError("WCL API points are below the safety reserve; request was not started.")
            self._reserved_points += required
            generation = self._rate_limit_generation
        try:
            yield
        finally:
            with self._rate_limit_lock:
                self._reserved_points -= required
                if generation == self._rate_limit_generation:
                    self._estimated_spent_points += required

    def _latest_rate_limit(self) -> dict[str, Any]:
        with self._rate_limit_lock:
            snapshot = dict(self._rate_limit_snapshot) if self._rate_limit_snapshot is not None else None
        return snapshot if snapshot is not None else self.rate_limit()

    def _update_rate_limit(self, value: dict[str, Any]) -> None:
        for field in ("limitPerHour", "pointsSpentThisHour", "pointsResetIn"):
            if isinstance(value.get(field), bool) or not isinstance(value.get(field), (int, float)):
                raise ApiError(f"WCL rate-limit field {field!r} is missing or invalid.")
        with self._rate_limit_lock:
            self._rate_limit_snapshot = dict(value)
            self._estimated_spent_points = 0.0
            self._rate_limit_generation += 1

    def _ensure_circuit(self) -> None:
        if self._rate_limit_tripped.is_set():
            raise RateLimitError("WCL API rate-limit circuit breaker is open; request was not started.")

    def _request_json(self, request: Request) -> dict[str, Any]:
        if not request.has_header("Accept-Encoding"):
            request.add_header("Accept-Encoding", "gzip")
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    content_encoding = response.headers.get("Content-Encoding")
                break
            except HTTPError as exc:
                if exc.code == 429:
                    self._rate_limit_tripped.set()
                    detail = exc.read().decode("utf-8", errors="replace")
                    raise RateLimitError(f"WCL HTTP 429: {detail[:500]}") from exc
                if exc.code in RETRYABLE_HTTP_STATUSES and attempt < self.max_retries:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    self._wait_before_retry(attempt, retry_after)
                    continue
                detail = exc.read().decode("utf-8", errors="replace")
                raise ApiError(f"WCL HTTP {exc.code}: {detail[:500]}") from exc
            except (URLError, TimeoutError, ConnectionError, http.client.HTTPException, ssl.SSLError) as exc:
                if attempt < self.max_retries:
                    self._wait_before_retry(attempt)
                    continue
                reason = exc.reason if isinstance(exc, URLError) else exc
                raise ApiError(f"Unable to reach WCL after {self.max_retries + 1} attempts: {reason}") from exc
        else:
            raise AssertionError("WCL request retry loop exited unexpectedly.")
        if isinstance(content_encoding, str) and content_encoding.strip().lower() == "gzip":
            try:
                raw = gzip.decompress(raw)
            except (EOFError, OSError, zlib.error) as exc:
                raise ApiError("WCL returned an invalid gzip response.") from exc
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("WCL returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise ApiError("WCL returned an unexpected JSON value.")
        return payload

    def _wait_before_retry(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self.retry_backoff_seconds * (2**attempt)
        if retry_after is not None:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    delay = max(delay, (retry_at - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass
        time.sleep(max(0.0, delay))
