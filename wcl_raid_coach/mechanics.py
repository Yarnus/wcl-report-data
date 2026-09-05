from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Protocol

from .coach_models import EncounterDesignator
from .errors import ApiError, InputError, RevisionChangedError
from .mechanic_rules import (
    RAID_ENCOUNTERS,
    RULESET_SOURCES,
    RULESET_VERSION,
    ZONE_ID,
    MechanicRule,
    build_filter_expression,
    encounter_name,
    rules_for,
)
from .models import ReportRef


class MechanicClient(Protocol):
    def fetch_report(self, code: str) -> tuple[dict[str, Any], dict[str, Any] | None]: ...

    def fetch_mechanic_events_page(
        self,
        code: str,
        fight_id: int,
        start_time: float,
        end_time: float,
        filter_expression: str,
    ) -> dict[str, Any]: ...

    def fetch_focused_events_page(
        self,
        code: str,
        fight_id: int,
        start_time: float,
        end_time: float,
        target_id: int,
    ) -> dict[str, Any]: ...

    def fetch_report_revision(self, code: str) -> int: ...


class MechanicReviewService:
    def __init__(self, client: MechanicClient) -> None:
        self.client = client

    def review(
        self, ref: ReportRef, *, encounter_designator: EncounterDesignator | None = None
    ) -> dict[str, Any]:
        report, rate_limit = self.client.fetch_report(ref.code)
        self._validate_report(report, ref.code)
        choices = self._fight_choices(report, encounter_designator)
        if ref.fight is None:
            return {
                "action": "coach_mechanics",
                "selection_required": True,
                "report_code": ref.code,
                "report_revision": report["revision"],
                "encounter_designator": (
                    encounter_designator.as_dict() if encounter_designator is not None else None
                ),
                "fight_choices": choices,
                "rate_limit": rate_limit,
            }
        if ref.fight == "last":
            raise InputError("Mechanic Review requires an explicit numeric fight ID, not fight=last.")
        fight = next(
            (
                item
                for item in report.get("fights") or []
                if isinstance(item, dict) and item.get("id") == ref.fight
            ),
            None,
        )
        if fight is None:
            raise InputError(f"Fight {ref.fight} is not present in report {ref.code}.")
        semantic_difficulty_id = self._validate_fight(fight, report)
        if encounter_designator is not None and ref.fight not in {item["fight_id"] for item in choices}:
            raise InputError("The numeric Boss Attempt does not match the Encounter Designator.")

        encounter_id = int(fight["encounterID"])
        difficulty_id = int(fight["difficulty"])
        rules = rules_for(encounter_id, semantic_difficulty_id)
        if not rules:
            raise InputError("Mechanic Review does not support this encounter and difficulty.")
        events, page_count = self._collect_events(
            ref.code,
            int(fight["id"]),
            float(fight["startTime"]),
            float(fight["endTime"]),
            build_filter_expression(rules),
        )
        revision = self.client.fetch_report_revision(ref.code)
        if type(revision) is not int:
            raise ApiError("WCL did not return a numeric report revision.")
        if revision != report["revision"]:
            raise RevisionChangedError(
                f"Report {ref.code} changed from revision {report['revision']} to {revision} during Mechanic Review."
            )
        actors = (report.get("masterData") or {}).get("actors") or []
        names = encounter_name(encounter_id)
        difficulty_name = _difficulty_names(report).get(difficulty_id)
        return {
            "action": "coach_mechanics",
            "selection_required": False,
            "identity": {
                "report_code": ref.code,
                "report_revision": revision,
                "fight_id": fight["id"],
                "encounter_id": encounter_id,
                "difficulty_id": difficulty_id,
            },
            "boss_attempt": {
                "name_en": names[0] if names else fight.get("name"),
                "name_zh": names[1] if names else None,
                "difficulty": difficulty_name,
                "kill": fight.get("kill"),
                "start_time": fight["startTime"],
                "end_time": fight["endTime"],
            },
            "ruleset": {
                "version": RULESET_VERSION,
                "selection_policy": "latest",
                "sources": list(RULESET_SOURCES),
            },
            "evidence": {
                "class": "mechanic_evidence_set",
                "storage": "process_memory",
                "filter_expression": build_filter_expression(rules),
                "event_count": len(events),
                "page_count": page_count,
                "pagination_terminated": True,
                "report_revision_checked_before_and_after": True,
            },
            "mechanics": evaluate_rules(
                encounter_id,
                semantic_difficulty_id,
                events,
                actors,
                float(fight["startTime"]),
                float(fight["endTime"]),
            ),
            "judgment": None,
            "causal_attribution": None,
        }

    def focused_evidence(
        self,
        ref: ReportRef,
        *,
        at_ms: float,
        window_ms: float,
        player_ids: list[int],
    ) -> dict[str, Any]:
        report, rate_limit = self.client.fetch_report(ref.code)
        self._validate_report(report, ref.code)
        if ref.fight is None or ref.fight == "last":
            raise InputError("Focused evidence requires an explicit numeric fight ID.")
        fight = next((item for item in report["fights"] if item.get("id") == ref.fight), None)
        if fight is None:
            raise InputError(f"Fight {ref.fight} is not present in report {ref.code}.")
        self._validate_fight(fight, report)
        if not _is_finite_number(at_ms) or at_ms < 0:
            raise InputError("--at-ms must be a finite non-negative number.")
        if not _is_finite_number(window_ms) or window_ms <= 0:
            raise InputError("--window-ms must be a finite positive number.")
        if window_ms > 30_000:
            raise InputError("--window-ms cannot exceed 30000 milliseconds.")
        if not player_ids or any(type(player_id) is not int or player_id <= 0 for player_id in player_ids):
            raise InputError("Focused evidence requires one or more positive --player-id values.")
        if len(set(player_ids)) != len(player_ids):
            raise InputError("Focused evidence player IDs must be unique.")

        actors = (report["masterData"] or {}).get("actors") or []
        actors_by_id = {
            actor.get("id"): actor
            for actor in actors
            if isinstance(actor, dict) and type(actor.get("id")) is int
        }
        participants = set(fight.get("friendlyPlayers") or [])
        if any(player_id not in participants for player_id in player_ids):
            raise InputError("Every focused evidence player must be a Boss Attempt participant.")

        duration = float(fight["endTime"]) - float(fight["startTime"])
        from_ms = max(0.0, float(at_ms) - float(window_ms))
        to_ms = min(duration, float(at_ms) + float(window_ms))
        if float(at_ms) > duration:
            raise InputError("--at-ms is outside the Boss Attempt range.")
        fetched_events: list[dict[str, Any]] = []
        page_count = 0
        for player_id in player_ids:
            player_events, player_pages = self._collect_focused_events(
                ref.code,
                int(fight["id"]),
                float(fight["startTime"]) + from_ms,
                float(fight["startTime"]) + to_ms,
                player_id,
            )
            fetched_events.extend(player_events)
            page_count += player_pages
        fetched_events.sort(key=lambda event: float(event["timestamp"]))
        selected_players = set(player_ids)
        events = [
            event for event in fetched_events
            if event.get("targetID") in selected_players and event.get("type") in _FOCUSED_EVENT_TYPES
        ]
        revision = self.client.fetch_report_revision(ref.code)
        if type(revision) is not int:
            raise ApiError("WCL did not return a numeric report revision.")
        if revision != report["revision"]:
            raise RevisionChangedError(
                f"Report {ref.code} changed from revision {report['revision']} to {revision} during focused evidence collection."
            )
        names = encounter_name(int(fight["encounterID"]))
        return {
            "action": "coach_evidence",
            "identity": {
                "report_code": ref.code,
                "report_revision": revision,
                "fight_id": fight["id"],
                "encounter_id": fight["encounterID"],
                "difficulty_id": fight["difficulty"],
            },
            "boss_attempt": {
                "name_en": names[0] if names else fight.get("name"),
                "name_zh": names[1] if names else None,
                "kill": fight["kill"],
            },
            "window": {"at_ms": float(at_ms), "from_ms": from_ms, "to_ms": to_ms},
            "players": [
                {"actor_id": player_id, "name": actors_by_id.get(player_id, {}).get("name")}
                for player_id in player_ids
            ],
            "evidence": {
                "class": "focused_event_window",
                "storage": "process_memory",
                "server_filter": "target_id",
                "event_types": list(_FOCUSED_EVENT_TYPES),
                "fetched_event_count": len(fetched_events),
                "event_count": len(events),
                "page_count": page_count,
                "pagination_terminated": True,
                "report_revision_checked_before_and_after": True,
            },
            "events": [_focused_event(event, float(fight["startTime"])) for event in events],
            "rate_limit": rate_limit,
            "judgment": None,
            "causal_attribution": None,
        }

    def _validate_report(self, report: Any, code: str) -> None:
        if not isinstance(report, dict) or report.get("code") != code:
            raise ApiError("WCL returned an invalid report for Mechanic Review.")
        if report.get("visibility") not in {"public", "unlisted"}:
            raise InputError("Only public and unlisted WCL reports are supported.")
        if type(report.get("revision")) is not int:
            raise ApiError("WCL did not return a numeric report revision.")
        master_data = report.get("masterData")
        zone = report.get("zone")
        archive = report.get("archiveStatus")
        fights = report.get("fights")
        if not isinstance(master_data, dict) or not isinstance(zone, dict):
            raise ApiError("WCL returned malformed report metadata for Mechanic Review.")
        if type(master_data.get("gameVersion")) is not int or master_data["gameVersion"] != 1:
            raise InputError("Mechanic Review supports Retail reports only.")
        if zone.get("id") != ZONE_ID:
            raise InputError("Mechanic Review currently supports The Venomous Abyss only.")
        if not isinstance(archive, dict):
            raise ApiError("WCL returned malformed archive metadata for Mechanic Review.")
        if archive.get("isArchived") is True and archive.get("isAccessible") is not True:
            raise InputError("Archived events are not accessible with the current WCL account.")
        actors = master_data.get("actors")
        difficulties = zone.get("difficulties")
        encounters = zone.get("encounters")
        if (
            not isinstance(actors, list)
            or any(not isinstance(item, dict) for item in actors)
            or not isinstance(difficulties, list)
            or any(not isinstance(item, dict) for item in difficulties)
            or not isinstance(encounters, list)
            or any(not isinstance(item, dict) for item in encounters)
            or not isinstance(fights, list)
            or any(not isinstance(item, dict) for item in fights)
        ):
            raise ApiError("WCL returned malformed report collections for Mechanic Review.")

    def _validate_fight(self, fight: dict[str, Any], report: dict[str, Any]) -> int:
        encounter_id = fight.get("encounterID")
        raw_difficulty_id = fight.get("difficulty")
        for field in ("id", "encounterID", "difficulty"):
            value = fight.get(field)
            if type(value) is not int:
                raise ApiError(f"WCL Boss Attempt field {field} is missing or invalid.")
        if encounter_id not in {item[0] for item in RAID_ENCOUNTERS}:
            raise InputError("The selected fight is not a supported Venomous Abyss Boss Attempt.")
        semantic_difficulty_id = _semantic_difficulty_id(report, raw_difficulty_id)
        if semantic_difficulty_id is None:
            raise InputError("Mechanic Review supports Normal, Heroic, and Mythic only.")
        if fight.get("inProgress") is not False:
            raise InputError("Mechanic Review requires a completed Boss Attempt.")
        if not isinstance(fight.get("kill"), bool):
            raise ApiError("WCL Boss Attempt field kill is missing or invalid.")
        for field in ("startTime", "endTime"):
            value = fight.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not _is_finite_number(value)
            ):
                raise ApiError(f"WCL Boss Attempt field {field} is missing or invalid.")
        if float(fight["startTime"]) > float(fight["endTime"]):
            raise ApiError("WCL Boss Attempt time range is invalid.")
        return semantic_difficulty_id

    def _fight_choices(
        self, report: dict[str, Any], designator: EncounterDesignator | None
    ) -> list[dict[str, Any]]:
        encounter_id = None
        difficulty_id = None
        if designator is not None:
            encounters = (report.get("zone") or {}).get("encounters") or []
            if designator.position > len(encounters):
                raise InputError("Encounter Designator is outside the report's zone ordering.")
            encounter = encounters[designator.position - 1]
            encounter_id = encounter.get("id") if isinstance(encounter, dict) else None
            difficulty_id = _difficulty_id(report, designator.difficulty_code)
        difficulty_names = _difficulty_names(report)
        choices = []
        for fight in report.get("fights") or []:
            if not isinstance(fight, dict):
                continue
            if fight.get("encounterID") not in {item[0] for item in RAID_ENCOUNTERS}:
                continue
            if (
                _semantic_difficulty_id(report, fight.get("difficulty")) is None
                or fight.get("inProgress") is not False
            ):
                continue
            if encounter_id is not None and fight.get("encounterID") != encounter_id:
                continue
            if difficulty_id is not None and fight.get("difficulty") != difficulty_id:
                continue
            self._validate_fight(fight, report)
            names = encounter_name(int(fight["encounterID"]))
            choices.append(
                {
                    "fight_id": fight.get("id"),
                    "encounter_id": fight.get("encounterID"),
                    "name_en": names[0] if names else fight.get("name"),
                    "name_zh": names[1] if names else None,
                    "difficulty_id": fight.get("difficulty"),
                    "difficulty": difficulty_names.get(fight.get("difficulty")),
                    "kill": fight.get("kill"),
                    "duration_ms": _duration(fight),
                }
            )
        return choices

    def _collect_events(
        self,
        code: str,
        fight_id: int,
        start_time: float,
        end_time: float,
        filter_expression: str,
    ) -> tuple[list[dict[str, Any]], int]:
        cursor = start_time
        seen_cursors: set[float] = set()
        events: list[dict[str, Any]] = []
        previous_timestamp: float | None = None
        page_count = 0
        while True:
            page = self.client.fetch_mechanic_events_page(
                code, fight_id, cursor, end_time, filter_expression
            )
            page_count += 1
            page_events = page.get("data") if isinstance(page, dict) else None
            if not isinstance(page_events, list) or any(not isinstance(item, dict) for item in page_events):
                raise ApiError("WCL returned an invalid Mechanic Evidence Set event page.")
            if "nextPageTimestamp" not in page:
                raise ApiError("WCL Mechanic Evidence Set page omitted nextPageTimestamp.")
            for event in page_events:
                timestamp = event.get("timestamp")
                if (
                    isinstance(timestamp, bool)
                    or not isinstance(timestamp, (int, float))
                    or not _is_finite_number(timestamp)
                ):
                    raise ApiError("A Mechanic Evidence Set event has an invalid timestamp.")
                if timestamp < cursor or timestamp > end_time:
                    raise ApiError("A Mechanic Evidence Set event is outside the Boss Attempt range.")
                if not isinstance(event.get("type"), str) or not event["type"]:
                    raise ApiError("A Mechanic Evidence Set event has an invalid type.")
                ability_id = event.get("abilityGameID")
                if type(ability_id) is not int and not (
                    event["type"] == "death" and ability_id is None
                ):
                    raise ApiError("A Mechanic Evidence Set event has an invalid ability ID.")
                for field in ("sourceID", "targetID", "extraAbilityGameID"):
                    value = event.get(field)
                    if value is not None and type(value) is not int:
                        raise ApiError(f"A Mechanic Evidence Set event has an invalid {field}.")
                if previous_timestamp is not None and timestamp < previous_timestamp:
                    raise ApiError("Mechanic Evidence Set events are not ordered by timestamp.")
                previous_timestamp = float(timestamp)
                events.append(event)
            next_cursor = page["nextPageTimestamp"]
            if next_cursor is None:
                return events, page_count
            if (
                isinstance(next_cursor, bool)
                or not isinstance(next_cursor, (int, float))
                or not _is_finite_number(next_cursor)
                or next_cursor <= cursor
                or next_cursor > end_time
                or float(next_cursor) in seen_cursors
            ):
                raise ApiError("WCL returned an invalid Mechanic Evidence Set pagination cursor.")
            seen_cursors.add(float(next_cursor))
            cursor = float(next_cursor)

    def _collect_focused_events(
        self,
        code: str,
        fight_id: int,
        start_time: float,
        end_time: float,
        target_id: int,
    ) -> tuple[list[dict[str, Any]], int]:
        cursor = start_time
        seen_cursors: set[float] = set()
        events: list[dict[str, Any]] = []
        previous_timestamp: float | None = None
        page_count = 0
        while True:
            page = self.client.fetch_focused_events_page(code, fight_id, cursor, end_time, target_id)
            page_count += 1
            page_events = page.get("data") if isinstance(page, dict) else None
            if not isinstance(page_events, list) or any(not isinstance(item, dict) for item in page_events):
                raise ApiError("WCL returned an invalid Focused Evidence Window page.")
            if "nextPageTimestamp" not in page:
                raise ApiError("Focused Evidence Window page omitted nextPageTimestamp.")
            for event in page_events:
                timestamp = event.get("timestamp")
                if (
                    isinstance(timestamp, bool)
                    or not isinstance(timestamp, (int, float))
                    or not _is_finite_number(timestamp)
                ):
                    raise ApiError("A Focused Evidence Window event has an invalid timestamp.")
                if timestamp < cursor or timestamp > end_time:
                    raise ApiError("A Focused Evidence Window event is outside the requested range.")
                if not isinstance(event.get("type"), str) or not event["type"]:
                    raise ApiError("A Focused Evidence Window event has an invalid type.")
                if previous_timestamp is not None and timestamp < previous_timestamp:
                    raise ApiError("Focused Evidence Window events are not ordered by timestamp.")
                previous_timestamp = float(timestamp)
                events.append(event)
            next_cursor = page["nextPageTimestamp"]
            if next_cursor is None:
                return events, page_count
            if (
                isinstance(next_cursor, bool)
                or not isinstance(next_cursor, (int, float))
                or not _is_finite_number(next_cursor)
                or next_cursor <= cursor
                or next_cursor > end_time
                or float(next_cursor) in seen_cursors
            ):
                raise ApiError("WCL returned an invalid Focused Evidence Window pagination cursor.")
            seen_cursors.add(float(next_cursor))
            cursor = float(next_cursor)


def evaluate_rules(
    encounter_id: int,
    difficulty_id: int,
    events: list[dict[str, Any]],
    actors: Iterable[dict[str, Any]],
    fight_start: float,
    fight_end: float | None = None,
) -> list[dict[str, Any]]:
    actors_by_id = {
        actor.get("id"): actor
        for actor in actors
        if isinstance(actor, dict) and isinstance(actor.get("id"), int)
    }
    results = []
    for rule in rules_for(encounter_id, difficulty_id):
        if rule.evaluation == "helical":
            result = _evaluate_helical(rule, events, actors_by_id, fight_start, difficulty_id)
        elif rule.evaluation == "turbulent":
            result = _evaluate_turbulent(
                rule, events, actors_by_id, fight_start, fight_end, difficulty_id
            )
        else:
            result = _evaluate_signals(rule, events, actors_by_id, fight_start, difficulty_id)
        results.append(result)
    return results


def _evaluate_signals(
    rule: MechanicRule,
    events: list[dict[str, Any]],
    actors: dict[int, dict[str, Any]],
    fight_start: float,
    difficulty_id: int,
) -> dict[str, Any]:
    relevant = [event for event in events if _ability_id(event) in rule.ability_ids]
    opportunities = _matching(events, rule.opportunity_signals)
    successes = _matching(events, rule.success_signals)
    if rule.evaluation == "interrupt":
        opportunity_ids = {signal[0] for signal in rule.opportunity_signals}
        successes = [
            event
            for event in events
            if event.get("type") == "interrupt" and event.get("extraAbilityGameID") in opportunity_ids
        ]
    failure_events = _matching(events, rule.failure_signals)
    verified = difficulty_id in rule.verified_difficulties
    anomalies = (
        _anomalies(failure_events, rule.scope, actors, fight_start)
        if verified and rule.evaluation != "observation"
        else []
    )
    return _base_rule(rule, difficulty_id) | {
        "anomaly_detection": (
            "event_pattern_unverified"
            if not verified
            else "not_applicable"
            if not rule.failure_signals or rule.evaluation == "observation"
            else "enabled"
        ),
        "summary": {
            "trigger_count": len(opportunities) if rule.opportunity_signals else len(relevant),
            "success_count": (
                len(successes)
                if verified and (rule.success_signals or rule.evaluation == "interrupt")
                else None
            ),
            "failure_count": len(anomalies) if verified and rule.evaluation != "observation" else None,
            "observed_events": len(relevant),
            "opportunities": len(opportunities) if rule.opportunity_signals else None,
            "success_signals": len(successes) if rule.success_signals or rule.evaluation == "interrupt" else None,
            "failure_signals": (
                len(failure_events)
                if rule.failure_signals and rule.evaluation != "observation"
                else None
            ),
        },
        "anomalies": anomalies,
    }


def _evaluate_helical(
    rule: MechanicRule,
    events: list[dict[str, Any]],
    actors: dict[int, dict[str, Any]],
    fight_start: float,
    difficulty_id: int,
) -> dict[str, Any]:
    verified = difficulty_id in rule.verified_difficulties
    applications = _matching(events, rule.opportunity_signals)
    removals = _matching(events, rule.success_signals)
    coincident_removal_pairs = sum(len(group) // 2 for group in _timestamp_groups(removals, 1.0))
    failures = _matching(events, rule.failure_signals)
    episodes = _timestamp_groups(failures, 250.0)
    anomalies = []
    if verified:
        for episode_number, episode in enumerate(episodes, start=1):
            for event in episode:
                anomalies.append(
                    _target_anomaly(event, actors, fight_start)
                    | {"outcome": "cultivated_burst", "episode": episode_number}
                )
    failed_targets = {event.get("targetID") for event in failures if isinstance(event.get("targetID"), int)}
    return _base_rule(rule, difficulty_id) | {
        "anomaly_detection": "enabled" if verified else "event_pattern_unverified",
        "summary": {
            "trigger_count": len(applications),
            "success_count": coincident_removal_pairs * 2 if verified else None,
            "failure_count": len(failures) if verified else None,
            "participants": len({event.get("targetID") for event in applications}),
            "coincident_removal_pairs": coincident_removal_pairs,
            "failed_participants": len(failed_targets),
            "failure_episodes": len(episodes),
        },
        "anomalies": anomalies,
    }


def _evaluate_turbulent(
    rule: MechanicRule,
    events: list[dict[str, Any]],
    actors: dict[int, dict[str, Any]],
    fight_start: float,
    fight_end: float | None,
    difficulty_id: int,
) -> dict[str, Any]:
    verified = difficulty_id in rule.verified_difficulties
    applications = _matching(events, rule.opportunity_signals)
    removals = _matching(events, rule.success_signals)
    starts: dict[int, list[dict[str, Any]]] = {}
    for event in applications:
        target = event.get("targetID")
        if isinstance(target, int):
            starts.setdefault(target, []).append(event)
    deaths = [event for event in events if event.get("type") == "death"]
    application_ids = {id(event) for event in applications}
    removal_ids = {id(event) for event in removals}
    active: dict[int, dict[str, Any]] = {}
    death_applications: set[tuple[int, float]] = set()
    anomalies = []
    for event in sorted(
        applications + removals + deaths,
        key=lambda item: (
            float(item["timestamp"]),
            0 if id(item) in application_ids else 1 if item.get("type") == "death" else 2,
        ),
    ):
        target = event.get("targetID")
        if not isinstance(target, int):
            continue
        if id(event) in application_ids:
            active[target] = event
        elif event.get("type") == "death" and target in active:
            application = active.pop(target)
            applied_at = float(application["timestamp"])
            timestamp = float(event["timestamp"])
            death_applications.add((target, applied_at))
            anomalies.append(
                _target_anomaly(event, actors, fight_start)
                | {
                    "outcome": "death",
                    "aura_duration_ms": timestamp - applied_at,
                    "aura_application_raw_event": dict(application),
                }
            )
        elif id(event) in removal_ids:
            active.pop(target, None)

    coincident_removal_pairs = 0
    successful_removals = 0
    unpaired_groups: list[list[dict[str, Any]]] = []
    for group in _timestamp_groups(removals, 1.0):
        surviving_removals = []
        death_removals = 0
        for event in group:
            target = event.get("targetID")
            application = _latest_application(starts.get(target, []), float(event["timestamp"]))
            application_key = (
                (target, float(application["timestamp"]))
                if isinstance(target, int) and application is not None
                else None
            )
            if application_key in death_applications:
                death_removals += 1
            else:
                surviving_removals.append(event)
        coincident_removal_pairs += len(group) // 2
        if len(group) % 2 and death_removals == 0:
            successful_removals += len(surviving_removals) - 1
            unpaired_groups.append(surviving_removals)
        else:
            successful_removals += len(surviving_removals)
    for group in unpaired_groups if verified else []:
        if len(group) > 1:
            anomalies.append(
                _team_anomaly(group, actors, fight_start)
                | {"outcome": "ambiguous_unpaired_removal"}
            )
            continue
        event = group[0]
        timestamp = float(event["timestamp"])
        if fight_end is not None and abs(timestamp - fight_end) <= 100:
            continue
        target = event.get("targetID")
        application = _latest_application(starts.get(target, []), timestamp)
        applied_at = float(application["timestamp"]) if application is not None else None
        duration = timestamp - applied_at if applied_at is not None else None
        outcome = "aura_expired" if duration is not None and duration >= 5_900 else "unpaired_removal"
        anomalies.append(
            _target_anomaly(event, actors, fight_start)
            | {
                "outcome": outcome,
                "aura_duration_ms": duration,
                "aura_application_raw_event": dict(application) if application is not None else None,
            }
        )
    if not verified:
        anomalies.clear()
    anomalies.sort(key=lambda item: float(item["time_ms"]))
    return _base_rule(rule, difficulty_id) | {
        "anomaly_detection": "enabled" if verified else "event_pattern_unverified",
        "summary": {
            "trigger_count": len(applications),
            "success_count": successful_removals if verified else None,
            "failure_count": len(anomalies) if verified else None,
            "applications": len(applications),
            "coincident_removal_pairs": coincident_removal_pairs,
            "unresolved_outcomes": len(anomalies),
        },
        "anomalies": anomalies,
    }


def _base_rule(rule: MechanicRule, difficulty_id: int) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "name_en": rule.name_en,
        "name_zh": rule.name_zh,
        "validation_status": (
            "verified" if difficulty_id in rule.verified_difficulties else "event_pattern_unverified"
        ),
        "expectation": rule.expectation,
        "ability_ids": list(rule.ability_ids),
    }


def _matching(events: list[dict[str, Any]], signals: tuple[tuple[int, tuple[str, ...]], ...]) -> list[dict[str, Any]]:
    if not signals:
        return []
    return [
        event
        for event in events
        if any(
            _ability_id(event) == ability_id and (not event_types or event.get("type") in event_types)
            for ability_id, event_types in signals
        )
    ]


def _anomalies(
    events: list[dict[str, Any]], scope: str, actors: dict[int, dict[str, Any]], fight_start: float
) -> list[dict[str, Any]]:
    if scope == "team":
        return [_team_anomaly(group, actors, fight_start) for group in _team_groups(events)]
    return [_target_episode(group, actors, fight_start) for group in _target_groups(events)]


def _target_groups(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups_by_key: dict[tuple[Any, int | None], list[list[dict[str, Any]]]] = {}
    for event in sorted(events, key=lambda item: float(item.get("timestamp", 0))):
        key = (event.get("targetID"), _ability_id(event))
        groups = groups_by_key.setdefault(key, [])
        if groups and float(event["timestamp"]) - float(groups[-1][-1]["timestamp"]) <= 1_500:
            groups[-1].append(event)
        else:
            groups.append([event])
    return sorted(
        (group for groups in groups_by_key.values() for group in groups),
        key=lambda group: float(group[0]["timestamp"]),
    )


def _team_groups(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[tuple[int | None, int], list[dict[str, Any]]] = {}
    for event in events:
        key = (_ability_id(event), int(float(event["timestamp"]) // 250))
        groups.setdefault(key, []).append(event)
    return sorted(groups.values(), key=lambda group: float(group[0]["timestamp"]))


def _timestamp_groups(events: list[dict[str, Any]], window_ms: float) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for event in sorted(events, key=lambda item: float(item["timestamp"])):
        if groups and float(event["timestamp"]) - float(groups[-1][-1]["timestamp"]) <= window_ms:
            groups[-1].append(event)
        else:
            groups.append([event])
    return groups


def _latest_application(
    applications: list[dict[str, Any]], timestamp: float
) -> dict[str, Any] | None:
    return next(
        (
            event
            for event in reversed(applications)
            if float(event["timestamp"]) <= timestamp
        ),
        None,
    )


def _target_episode(
    events: list[dict[str, Any]], actors: dict[int, dict[str, Any]], fight_start: float
) -> dict[str, Any]:
    first = events[0]
    result = _target_anomaly(first, actors, fight_start)
    result["event_count"] = len(events)
    if len(events) > 1:
        result["end_time_ms"] = float(events[-1]["timestamp"]) - fight_start
    return result


def _target_anomaly(
    event: dict[str, Any], actors: dict[int, dict[str, Any]], fight_start: float
) -> dict[str, Any]:
    return {
        "time_ms": float(event["timestamp"]) - fight_start,
        "event_type": event.get("type"),
        "ability_id": _ability_id(event),
        "actor": _actor(event.get("targetID"), actors),
        "raw_event": dict(event),
    }


def _team_anomaly(
    events: list[dict[str, Any]], actors: dict[int, dict[str, Any]], fight_start: float
) -> dict[str, Any]:
    first = events[0]
    targets = sorted({event.get("targetID") for event in events if isinstance(event.get("targetID"), int)})
    return {
        "time_ms": float(first["timestamp"]) - fight_start,
        "event_type": first.get("type"),
        "ability_id": _ability_id(first),
        "event_count": len(events),
        "actors": [_actor(target, actors) for target in targets],
        "raw_events": [dict(event) for event in events],
    }


def _actor(actor_id: Any, actors: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(actor_id, int):
        return None
    value = actors.get(actor_id) or {}
    return {"actor_id": actor_id, "name": value.get("name"), "type": value.get("type")}


def compact_mechanic_review(review: dict[str, Any]) -> dict[str, Any]:
    if review.get("selection_required") is True:
        return dict(review) | {"output_mode": "compact"}
    compact = {key: value for key, value in review.items() if key != "mechanics"}
    compact["output_mode"] = "compact"
    compact["mechanics"] = []
    for mechanic in review.get("mechanics") or []:
        if not isinstance(mechanic, dict):
            continue
        item = {key: value for key, value in mechanic.items() if key != "anomalies"}
        anomalies = mechanic.get("anomalies") or []
        player_anomalies = []
        suppressed_records = 0
        suppressed_events = 0
        for anomaly in anomalies:
            if not isinstance(anomaly, dict):
                continue
            actor = anomaly.get("actor")
            actors = anomaly.get("actors")
            has_player = (
                isinstance(actor, dict) and actor.get("type") == "Player"
            ) or (
                isinstance(actors, list)
                and any(isinstance(value, dict) and value.get("type") == "Player" for value in actors)
            )
            if not has_player:
                suppressed_records += 1
                count = anomaly.get("event_count", 1)
                suppressed_events += count if type(count) is int and count >= 0 else 1
                continue
            sanitized = {
                key: value
                for key, value in anomaly.items()
                if key not in {"raw_event", "raw_events"}
            }
            if isinstance(actors, list):
                sanitized["actors"] = [
                    value for value in actors
                    if isinstance(value, dict) and value.get("type") == "Player"
                ]
            player_anomalies.append(sanitized)
        item["anomalies"] = player_anomalies[:20]
        if suppressed_records:
            item["suppressed_anomalies"] = {
                "pet_or_npc_records": suppressed_records,
                "event_count": suppressed_events,
            }
        if len(player_anomalies) > 20:
            item["suppressed_player_anomalies"] = len(player_anomalies) - 20
        compact["mechanics"].append(item)
    return compact


_FOCUSED_EVENT_TYPES = (
    "damage", "heal", "absorbed", "applybuff", "removebuff",
    "applydebuff", "removedebuff", "death", "resurrect",
)


def _focused_event(event: dict[str, Any], fight_start: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "fight_time_ms": float(event["timestamp"]) - fight_start,
        "type": event["type"],
    }
    fields = {
        "sourceID": "source_id",
        "targetID": "target_id",
        "abilityGameID": "ability_id",
        "extraAbilityGameID": "extra_ability_id",
        "amount": "amount",
        "absorbed": "absorbed",
        "overheal": "overheal",
        "overkill": "overkill",
        "hitPoints": "hit_points",
        "maxHitPoints": "max_hit_points",
        "killerID": "killer_id",
        "killingAbilityGameID": "killing_ability_id",
        "stack": "stack",
    }
    for source, target in fields.items():
        value = event.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and _is_finite_number(value):
            result[target] = value
    return result


def _ability_id(event: dict[str, Any]) -> int | None:
    value = event.get("abilityGameID")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    ability = event.get("ability")
    if isinstance(ability, dict):
        value = ability.get("gameID") or ability.get("guid") or ability.get("id")
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    return None


def _difficulty_names(report: dict[str, Any]) -> dict[int, str]:
    return {
        item.get("id"): item.get("name")
        for item in (report.get("zone") or {}).get("difficulties") or []
        if isinstance(item, dict)
        and isinstance(item.get("id"), int)
        and isinstance(item.get("name"), str)
    }


def _semantic_difficulty_id(report: dict[str, Any], raw_id: Any) -> int | None:
    if type(raw_id) is not int:
        return None
    name = _difficulty_names(report).get(raw_id)
    return {"normal": 3, "heroic": 4, "mythic": 5}.get(name.casefold()) if name else None


def _difficulty_id(report: dict[str, Any], code: str) -> int:
    expected = {"PT": "normal", "H": "heroic", "M": "mythic"}[code]
    matches = [
        difficulty_id
        for difficulty_id, name in _difficulty_names(report).items()
        if name.casefold() == expected
    ]
    if len(matches) != 1:
        raise InputError(f"The report does not define exactly one {expected.title()} difficulty.")
    return matches[0]


def _duration(fight: dict[str, Any]) -> float | None:
    start = fight.get("startTime")
    end = fight.get("endTime")
    if all(_is_finite_number(value) for value in (start, end)):
        return float(end) - float(start)
    return None


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
