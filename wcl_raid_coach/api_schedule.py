"""Serialize this OS user's WCL HTTP attempts across dataset roots and clients."""
from __future__ import annotations

import json
import math
import os
import time
from contextlib import contextmanager
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError

from .dataset import _file_lock
from .errors import ApiError, DatasetError, RateLimitError
from .storage import atomic_write_json, read_json


def coordination_root() -> Path:
    if os.name == "nt":
        import ctypes
        buffer = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x28, None, 0, buffer) != 0:
            raise ApiError("Unable to resolve the OS user's profile directory.")
        home = buffer.value
    else:
        import pwd
        try:
            home = pwd.getpwuid(os.getuid()).pw_dir
        except KeyError as exc:
            raise ApiError("Unable to resolve the OS user's home directory.") from exc
    return Path(home) / ".wcl-report-data" / "api"


@contextmanager
def _http_lock(root):
    lock = _file_lock(root / "schedule.lock", timeout_seconds=10,
                      unavailable_message="Timed out waiting for the shared WCL HTTP gate.")
    try:
        lock.__enter__()
    except DatasetError as exc:
        raise RateLimitError(str(exc)) from exc
    except OSError as exc:
        raise ApiError("Unable to acquire the shared WCL HTTP lock.") from exc
    try:
        yield
    finally:
        try:
            lock.__exit__(None, None, None)
        except OSError as exc:
            raise ApiError("Unable to release the shared WCL HTTP lock.") from exc


def _number(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _quota(value) -> dict:
    fields = {"limitPerHour", "pointsSpentThisHour", "pointsResetIn"}
    if not isinstance(value, dict) or any(not _number(value.get(key)) for key in fields) or value["limitPerHour"] <= 0:
        raise ApiError("WCL quota observation is invalid.")
    return {key: value[key] for key in fields}


class ApiSchedule:
    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else coordination_root()
        self.state = None
        self.cached = None

    def _load(self):
        path = self.root / "state.json"
        wall, monotonic = time.time(), time.monotonic()
        if not path.exists():
            return {"schema_version": 1, "quota": None, "observed_at": 0.0,
                    "estimated_points": 0.0, "cooldown_until": 0.0,
                    "in_flight": False, "needs_refresh": True,
                    "updated_at": wall, "clock_baseline": wall - monotonic}
        try:
            value = read_json(path)
            keys = {"schema_version", "quota", "observed_at", "estimated_points", "cooldown_until",
                    "in_flight", "needs_refresh", "updated_at", "clock_baseline"}
            if not isinstance(value, dict) or set(value) != keys or type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise ValueError()
            if any(not _number(value[key]) for key in ("observed_at", "estimated_points", "cooldown_until", "updated_at", "clock_baseline")):
                raise ValueError()
            if type(value["in_flight"]) is not bool or type(value["needs_refresh"]) is not bool:
                raise ValueError()
            if value["quota"] is not None:
                value["quota"] = _quota(value["quota"])
            if wall < value["updated_at"] - 1 or abs(wall - monotonic - value["clock_baseline"]) > 5:
                raise ValueError()
            if value["observed_at"] > value["updated_at"]:
                raise ValueError()
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ApiError) as exc:
            raise RateLimitError("Shared WCL scheduling state is invalid or its clock continuity is unavailable.") from exc
        if value["in_flight"]:
            value["needs_refresh"] = True
        return value

    def _save(self):
        self.state["updated_at"] = time.time()
        try:
            atomic_write_json(self.root / "state.json", self.state)
        except OSError as exc:
            raise ApiError("Unable to persist shared WCL scheduling state.") from exc

    def _fresh(self):
        quota = self.state["quota"]
        return quota is not None and not self.state["needs_refresh"] and (
            time.time() < self.state["observed_at"] + quota["pointsResetIn"]
        )

    @contextmanager
    def attempt(self, operation: str):
        try:
            with _http_lock(self.root):
                self.state = self._load()
                self.cached = None
                now = time.time()
                if self.state["cooldown_until"] > now:
                    raise RateLimitError(f"WCL shared cooldown is active until Unix time {self.state['cooldown_until']:.3f}.")
                fresh = self._fresh()
                required = 500.0 if operation == "ReportIndex" else 10.0
                if operation == "OAuth":
                    required = 0.0
                if fresh:
                    quota = self.state["quota"]
                    remaining = quota["limitPerHour"] - quota["pointsSpentThisHour"] - self.state["estimated_points"]
                    if operation == "RateLimit":
                        self.cached = {"_shared_quota": True, "data": {"rateLimitData": quota | {
                            "pointsSpentThisHour": quota["pointsSpentThisHour"] + self.state["estimated_points"],
                            "pointsResetIn": max(0.0, self.state["observed_at"] + quota["pointsResetIn"] - now),
                        }}}
                        yield self
                        return
                    if remaining - required < max(50.0, quota["limitPerHour"] * 0.15):
                        reset_at = self.state["observed_at"] + quota["pointsResetIn"]
                        raise RateLimitError(f"WCL shared budget is below the safety reserve; reset expected at Unix time {reset_at:.3f}.")
                elif operation not in ("OAuth", "RateLimit"):
                    raise RateLimitError("Shared WCL quota needs a coordinated refresh; run doctor before retrying.")
                self.state["estimated_points"] += required
                self.state["in_flight"] = True
                self._save()
                try:
                    yield self
                except HTTPError as exc:
                    if exc.code == 429:
                        self.rate_limited(exc.headers)
                    raise
                finally:
                    self.state["in_flight"] = False
                    self._save()
        except DatasetError as exc:
            raise RateLimitError(str(exc)) from exc

    def observe(self, payload: dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("rateLimitData"), dict):
            self.state["quota"] = _quota(data["rateLimitData"])
            self.state["observed_at"] = time.time()
            self.state["estimated_points"] = 0.0
            self.state["needs_refresh"] = False
            self.state["cooldown_until"] = 0.0

    def rate_limited(self, headers):
        now = time.time()
        retry_after = headers.get("Retry-After") if headers else None
        until = None
        if isinstance(retry_after, str):
            try:
                seconds = float(retry_after)
                if _number(seconds):
                    until = now + seconds
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(retry_after)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    until = max(now, parsed.timestamp())
                except (ValueError, TypeError, OverflowError):
                    pass
        quota = self.state["quota"]
        if until is None and quota is not None:
            reset_at = self.state["observed_at"] + quota["pointsResetIn"]
            if reset_at > now:
                until = reset_at
        self.state["cooldown_until"] = until if until is not None else now + 60
        self.state["needs_refresh"] = True
        self._save()
