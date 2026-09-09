"""Opt-in, process-local measurements containing only fixed labels and numbers."""
from __future__ import annotations

import math
from time import monotonic
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps


_current: ContextVar[Measurements | None] = ContextVar("diagnostics", default=None)


class Measurements:
    def __init__(self):
        self.network = {}
        self.stages = {}
        self.counters = {}
        self.quota = {"observations": 0, "first": None, "last": None, "attributable_cost": None}
        self.stack = []

    def snapshot(self):
        return {
            "kind": "wcl_diagnostics", "schema_version": 1,
            "clock": "monotonic", "network": self.network, "stages": self.stages,
            "counters": self.counters, "quota": self.quota,
            "agent_synthesis": "not_measured", "delivery_guarantee": False,
        }


@contextmanager
def collect():
    measurements = Measurements()
    token = _current.set(measurements)
    try:
        yield measurements
    finally:
        _current.reset(token)


@contextmanager
def stage(name):
    measurements = _current.get()
    if measurements is None:
        yield
        return
    start = monotonic()
    frame = [0.0]
    measurements.stack.append(frame)
    try:
        yield
    finally:
        elapsed = monotonic() - start
        measurements.stack.pop()
        if measurements.stack:
            measurements.stack[-1][0] += elapsed
        value = measurements.stages.setdefault(name, {"calls": 0, "seconds": 0.0, "exclusive_seconds": 0.0})
        value["calls"] += 1
        value["seconds"] += elapsed
        value["exclusive_seconds"] += max(0.0, elapsed - frame[0])


def measured(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


@contextmanager
def network_attempt(operation, attempt):
    measurements = _current.get()
    body = {"response_body_bytes": 0}
    if measurements is None:
        yield body
        return
    start = monotonic()
    try:
        yield body
    finally:
        value = measurements.network.setdefault(operation, {
            "attempts": 0, "retries": 0, "response_body_bytes": 0, "seconds": 0.0,
        })
        value["attempts"] += 1
        value["retries"] += int(attempt > 0)
        value["response_body_bytes"] += body["response_body_bytes"]
        value["seconds"] += monotonic() - start


def count(name):
    measurements = _current.get()
    if measurements is not None:
        measurements.counters[name] = measurements.counters.get(name, 0) + 1


def copy_response_body(response, target, measurement):
    while chunk := response.read(64 * 1024):
        measurement["response_body_bytes"] += len(chunk)
        target.write(chunk)


def quota_snapshot(value):
    measurements = _current.get()
    if measurements is None:
        return
    fields = ("limitPerHour", "pointsSpentThisHour", "pointsResetIn")
    try:
        valid = all(type(value.get(key)) in (int, float) and math.isfinite(value[key]) for key in fields)
    except OverflowError:
        return
    if not valid:
        return
    snapshot = {key: value[key] for key in fields}
    quota = measurements.quota
    quota["observations"] += 1
    if quota["first"] is None:
        quota["first"] = snapshot
    quota["last"] = snapshot
