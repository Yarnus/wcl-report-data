from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from .errors import ApiError, DatasetError, InputError, RevisionChangedError
from .models import ReportRef
from .storage import atomic_write_gzip_json, atomic_write_json, directory_size, read_json, sha256_file


SCHEMA_VERSION = 1
RETAIL_GAME_VERSION = 1

COMMON_EVENT_FIELDS = {
    "timestamp",
    "type",
    "sourceID",
    "sourceInstance",
    "sourceInstanceID",
    "targetID",
    "targetInstance",
    "targetInstanceID",
    "ability",
    "abilityGameID",
}

DETAIL_EVENT_FIELDS = {
    "amount",
    "unmitigatedAmount",
    "absorbed",
    "absorb",
    "blocked",
    "overkill",
    "overheal",
    "effectiveHealing",
    "mitigated",
    "isAoE",
    "hitType",
    "missType",
    "tick",
    "multistrike",
    "critical",
    "resourceChange",
    "resourceChangeType",
    "waste",
    "maxResources",
    "maxResourceAmount",
    "otherResourceChange",
    "resourceActor",
    "classResources",
    "sourceResources",
    "targetResources",
    "hitPoints",
    "maxHitPoints",
    "stack",
    "stackSize",
    "duration",
    "empowermentLevel",
    "extraAbilityGameID",
    "extraAttacks",
    "killerID",
    "healerID",
    "friendly",
    "fake",
    "melee",
    "fight",
    "packetID",
    "attackerID",
    "attackerInstance",
    "targetMarker",
    "sourceMarker",
    "encounterID",
    "difficulty",
    "name",
    "size",
    "mapID",
    "x",
    "y",
    "facing",
    "itemLevel",
    "gear",
    "auras",
    "talents",
    "pvpTalents",
    "talentTree",
    "specID",
    "faction",
    "expansion",
    "strength",
    "agility",
    "stamina",
    "intellect",
    "armor",
    "attackPower",
    "spellPower",
    "critMelee",
    "critRanged",
    "critSpell",
    "hasteMelee",
    "hasteRanged",
    "hasteSpell",
    "mastery",
    "versatility",
    "versatilityDamageDone",
    "versatilityDamageReduction",
    "versatilityHealingDone",
    "leech",
    "avoidance",
    "speed",
    "dodge",
    "parry",
    "block",
    "customPowerSet",
    "secondaryCustomPowerSet",
    "tertiaryCustomPowerSet",
}


class DatasetClient(Protocol):
    def fetch_report(self, code: str) -> tuple[dict[str, Any], dict[str, Any] | None]: ...

    def fetch_events_page(
        self, code: str, fight_id: int, start_time: float | None, limit: int = 10_000
    ) -> dict[str, Any]: ...

    def fetch_report_revision(self, code: str) -> int: ...


class DatasetStore:
    CACHE_MARKER = ".wcl-report-data-cache"

    def __init__(self, data_root: Path, cache_root: Path) -> None:
        self.data_root = data_root.expanduser()
        self.cache_root = cache_root.expanduser()

    def report_root(self, code: str) -> Path:
        return self.data_root / "reports" / code

    def revision_root(self, code: str, revision: int) -> Path:
        return self.report_root(code) / "revisions" / str(revision)

    def index_path(self, code: str, revision: int) -> Path:
        return self.revision_root(code, revision) / "report.json"

    def fight_root(self, code: str, revision: int, fight_id: int) -> Path:
        return self.revision_root(code, revision) / "fights" / str(fight_id)

    def import_root(self, code: str, revision: int, fight_id: int) -> Path:
        raw_root = self.cache_root / "raw"
        self._ensure_owned_cache(raw_root)
        return raw_root / code / str(revision) / str(fight_id)

    def write_index(self, index: dict[str, Any]) -> Path:
        code = str(index["report"]["code"])
        revision = int(index["report"]["revision"])
        path = self.index_path(code, revision)
        with self._latest_lock(code):
            if path.exists():
                existing = read_json(path)
                if _stable_index(existing) != _stable_index(index):
                    raise RevisionChangedError(
                        f"Report {code} changed without advancing revision {revision}; the existing index was preserved."
                    )
            else:
                atomic_write_json(path, index)
            self._update_latest_unlocked(code, revision)
        return path

    def list_datasets(self) -> dict[str, Any]:
        reports = []
        root = self.data_root / "reports"
        if root.exists():
            for latest in sorted(root.glob("*/latest.json")):
                try:
                    reports.append(read_json(latest))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        return {"data_root": str(self.data_root), "reports": reports, "bytes": directory_size(self.data_root)}

    def remove_dataset(self, code: str, revision: int | None = None) -> dict[str, Any]:
        if not code.isalnum():
            raise InputError("Report code must be alphanumeric.")
        target = self.report_root(code) if revision is None else self.revision_root(code, revision)
        with self._latest_lock(code):
            existed = target.exists()
            if existed:
                shutil.rmtree(target)
            if revision is not None:
                self._repair_latest_unlocked(code)
        return {"removed": existed, "path": str(target)}

    def cache_status(self) -> dict[str, Any]:
        raw_root = self.cache_root / "raw"
        files = sum(1 for item in raw_root.rglob("*") if item.is_file()) if raw_root.exists() else 0
        return {"cache_root": str(self.cache_root), "files": files, "bytes": directory_size(raw_root)}

    def clear_cache(self) -> dict[str, Any]:
        status = self.cache_status()
        raw_root = self.cache_root / "raw"
        if raw_root.exists():
            marker = raw_root / self.CACHE_MARKER
            if not marker.is_file():
                raise DatasetError(f"Refusing to clear unowned cache directory: {raw_root}")
            shutil.rmtree(raw_root)
        return {"cleared": True, "previous": status}

    def _ensure_owned_cache(self, raw_root: Path) -> None:
        marker = raw_root / self.CACHE_MARKER
        if raw_root.exists() and not marker.is_file() and any(raw_root.iterdir()):
            raise DatasetError(f"Refusing to use non-empty unowned cache directory: {raw_root}")
        raw_root.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            atomic_write_json(marker, {"owner": "wcl-report-data", "schema_version": SCHEMA_VERSION})

    def _repair_latest_unlocked(self, code: str) -> None:
        report_root = self.report_root(code)
        revisions_root = report_root / "revisions"
        latest = report_root / "latest.json"
        revisions = sorted(
            (int(item.name) for item in revisions_root.iterdir() if item.is_dir() and item.name.isdigit()),
            reverse=True,
        ) if revisions_root.exists() else []
        if not revisions:
            latest.unlink(missing_ok=True)
            return
        revision = revisions[0]
        atomic_write_json(
            latest,
            {
                "schema_version": SCHEMA_VERSION,
                "report_code": code,
                "revision": revision,
                "index_path": str(self.index_path(code, revision)),
            },
        )

    def _update_latest_unlocked(self, code: str, revision: int) -> None:
        latest = self.report_root(code) / "latest.json"
        if latest.exists():
            current = read_json(latest)
            current_revision = current.get("revision")
            if isinstance(current_revision, int) and current_revision > revision:
                return
        atomic_write_json(
            latest,
            {
                "schema_version": SCHEMA_VERSION,
                "report_code": code,
                "revision": revision,
                "index_path": str(self.index_path(code, revision)),
            },
        )

    @contextmanager
    def _latest_lock(self, code: str, timeout_seconds: float = 5.0) -> Iterator[None]:
        locks_root = self.data_root / ".locks"
        locks_root.mkdir(parents=True, exist_ok=True)
        lock_path = locks_root / f"{code}.lock"
        deadline = time.monotonic() + timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - lock_path.stat().st_mtime > 60:
                        lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise DatasetError(f"Timed out waiting for report index lock: {lock_path}")
                time.sleep(0.05)
        try:
            os.close(descriptor)
            descriptor = None
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            lock_path.unlink(missing_ok=True)


class DatasetService:
    def __init__(self, client: DatasetClient, store: DatasetStore) -> None:
        self.client = client
        self.store = store

    def inspect(self, ref: ReportRef) -> dict[str, Any]:
        report, rate_limit = self.client.fetch_report(ref.code)
        self._validate_report(report)
        fights = self._fight_summaries(report)
        selected_fight_id = self._resolve_url_fight(ref, fights)
        index = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "report": {
                key: report.get(key)
                for key in (
                    "code", "title", "visibility", "revision", "startTime", "endTime", "archiveStatus", "zone"
                )
            }
            | {
                "log_version": (report.get("masterData") or {}).get("logVersion"),
                "game_version": (report.get("masterData") or {}).get("gameVersion"),
                "locale": (report.get("masterData") or {}).get("lang"),
            },
            "actors": (report.get("masterData") or {}).get("actors") or [],
            "abilities": (report.get("masterData") or {}).get("abilities") or [],
            "fights": fights,
        }
        index_path = self.store.write_index(index)
        selected = next((fight for fight in fights if fight["fight_id"] == selected_fight_id), None)
        choices = [self._choice(fight) for fight in fights if fight["kind"] == "boss"]
        return {
            "ok": True,
            "action": "inspect",
            "report_code": report["code"],
            "revision": report["revision"],
            "index_path": str(index_path),
            "input_reference": ref.as_dict(),
            "selected_fight_id": selected_fight_id,
            "selected_fight": self._choice(selected) if selected else None,
            "fight_choices": choices,
            "rate_limit": rate_limit,
        }

    def prepare(
        self,
        ref: ReportRef,
        *,
        fight_ids: Iterable[int] | None = None,
        encounter_id: int | None = None,
        all_boss_fights: bool = False,
    ) -> dict[str, Any]:
        explicit_fights = list(fight_ids or [])
        selectors = sum((bool(explicit_fights), encounter_id is not None, all_boss_fights))
        if selectors > 1:
            raise InputError("Use only one of fight IDs, encounter ID, or all Boss fights.")
        if ref.fight is not None and selectors:
            raise InputError("A URL fight cannot be combined with another selector; use a bare report URL.")

        inspected = self.inspect(ref)
        index = read_json(Path(inspected["index_path"]))
        fights = index["fights"]
        fight_by_id = {fight["fight_id"]: fight for fight in fights}
        selected_ids: list[int]
        if explicit_fights:
            selected_ids = explicit_fights
        elif encounter_id is not None:
            selected_ids = [
                fight["fight_id"]
                for fight in fights
                if fight["encounter_id"] == encounter_id and fight["packable"]
            ]
            if not selected_ids:
                raise InputError(f"No completed packable Boss attempts use encounter ID {encounter_id}.")
        elif all_boss_fights:
            selected_ids = [fight["fight_id"] for fight in fights if fight["packable"]]
            if not selected_ids:
                raise InputError("The report has no completed packable Boss attempts.")
        elif inspected["selected_fight_id"] is not None:
            selected_ids = [int(inspected["selected_fight_id"])]
        else:
            raise InputError("No fight was selected. Inspect the report, then choose a fight, encounter, or all Boss fights.")

        bundles = []
        for fight_id in dict.fromkeys(selected_ids):
            fight = fight_by_id.get(fight_id)
            if fight is None:
                raise InputError(f"Fight {fight_id} is not present in report {ref.code}.")
            if not fight["packable"]:
                raise InputError(f"Fight {fight_id} cannot be prepared: {fight['unpackable_reason']}.")
            bundles.append(self._prepare_fight(index, fight))
        return {
            "ok": True,
            "action": "prepare",
            "report_code": ref.code,
            "revision": index["report"]["revision"],
            "index_path": inspected["index_path"],
            "bundles": bundles,
            "rate_limit": inspected["rate_limit"],
        }

    def _prepare_fight(self, index: dict[str, Any], fight: dict[str, Any]) -> dict[str, Any]:
        code = str(index["report"]["code"])
        revision = int(index["report"]["revision"])
        fight_id = int(fight["fight_id"])
        target = self.store.fight_root(code, revision, fight_id)
        manifest_path = target / "manifest.json"
        if manifest_path.exists():
            manifest = read_json(manifest_path)
            if manifest.get("complete") is True:
                expected_identity = {
                    "report_code": code,
                    "report_revision": revision,
                    "fight_id": fight_id,
                }
                if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("identity") != expected_identity:
                    raise DatasetError("Fight Bundle manifest identity does not match its dataset path.")
                _validate_bundle_file(manifest_path, manifest)
                return _bundle_result(manifest_path, manifest, cache_hit=True)

        import_root = self.store.import_root(code, revision, fight_id)
        import_root.mkdir(parents=True, exist_ok=True)
        checkpoint_path = import_root / "checkpoint.json"
        checkpoint = self._load_checkpoint(checkpoint_path, code, revision, fight_id)
        if not checkpoint["done"]:
            self._download_pages(checkpoint, checkpoint_path, import_root, code, fight_id)

        observed_revision = self.client.fetch_report_revision(code)
        if observed_revision != revision:
            raise RevisionChangedError(
                f"Report {code} changed from revision {revision} to {observed_revision} during collection."
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{fight_id}.", dir=target.parent))
        try:
            manifest = self._normalize_bundle(index, fight, checkpoint, temporary)
            atomic_write_json(temporary / "manifest.json", manifest)
            if target.exists():
                shutil.rmtree(target)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        manifest_path = target / "manifest.json"
        return _bundle_result(manifest_path, manifest, cache_hit=False)

    def _load_checkpoint(
        self, path: Path, code: str, revision: int, fight_id: int
    ) -> dict[str, Any]:
        if path.exists():
            value = read_json(path)
            identity = (value.get("report_code"), value.get("revision"), value.get("fight_id"))
            if identity != (code, revision, fight_id):
                raise DatasetError("Raw-page checkpoint identity does not match the requested fight.")
            for page in value.get("pages") or []:
                page_path = Path(page.get("path", ""))
                if page_path.parent.resolve() != path.parent.resolve() or not page_path.name.startswith("page-"):
                    raise DatasetError("Raw-page checkpoint points outside its import directory.")
                if not page_path.is_file() or sha256_file(page_path) != page.get("sha256"):
                    raise DatasetError(f"Raw-page cache failed checksum validation: {page_path}")
            return value
        return {
            "schema_version": SCHEMA_VERSION,
            "report_code": code,
            "revision": revision,
            "fight_id": fight_id,
            "next_page_timestamp": None,
            "seen_cursors": [],
            "pages": [],
            "event_count": 0,
            "done": False,
        }

    def _download_pages(
        self,
        checkpoint: dict[str, Any],
        checkpoint_path: Path,
        import_root: Path,
        code: str,
        fight_id: int,
    ) -> None:
        while not checkpoint["done"]:
            start_time = checkpoint["next_page_timestamp"]
            page = self.client.fetch_events_page(code, fight_id, start_time)
            events = page.get("data") if isinstance(page, dict) else None
            if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
                raise ApiError("WCL returned an invalid event page.")
            next_timestamp = page.get("nextPageTimestamp")
            if next_timestamp is not None:
                if not isinstance(next_timestamp, (int, float)) or isinstance(next_timestamp, bool):
                    raise ApiError("WCL returned an invalid nextPageTimestamp.")
                if next_timestamp == start_time or next_timestamp in checkpoint["seen_cursors"]:
                    raise ApiError(f"WCL event pagination stalled at {next_timestamp}.")

            page_number = len(checkpoint["pages"]) + 1
            page_path = import_root / f"page-{page_number:06d}.json.gz"
            atomic_write_gzip_json(page_path, page)
            checkpoint["pages"].append(
                {
                    "number": page_number,
                    "path": str(page_path),
                    "query_start_time": start_time,
                    "next_page_timestamp": next_timestamp,
                    "events": len(events),
                    "sha256": sha256_file(page_path),
                }
            )
            checkpoint["event_count"] += len(events)
            if next_timestamp is None:
                checkpoint["done"] = True
            else:
                checkpoint["seen_cursors"].append(next_timestamp)
                checkpoint["next_page_timestamp"] = next_timestamp
            atomic_write_json(checkpoint_path, checkpoint)

    def _normalize_bundle(
        self,
        index: dict[str, Any],
        fight: dict[str, Any],
        checkpoint: dict[str, Any],
        temporary: Path,
    ) -> dict[str, Any]:
        events_path = temporary / "events.jsonl.gz"
        unknown_fields: Counter[str] = Counter()
        event_types: Counter[str] = Counter()
        sequence = 0
        previous_timestamp: float | None = None
        with gzip.open(events_path, "wt", encoding="utf-8") as output:
            for page in checkpoint["pages"]:
                page_path = Path(page["path"])
                if sha256_file(page_path) != page.get("sha256"):
                    raise DatasetError(f"Raw-page cache changed during normalization: {page_path}")
                with gzip.open(page_path, "rt", encoding="utf-8") as handle:
                    raw_page = json.load(handle)
                for page_index, event in enumerate(raw_page["data"]):
                    canonical, unknown = _canonical_event(
                        event,
                        sequence=sequence,
                        fight_start=float(fight["start_time"]),
                        page_number=int(page["number"]),
                        page_index=page_index,
                    )
                    timestamp = canonical["report_time_ms"]
                    if previous_timestamp is not None and timestamp < previous_timestamp:
                        raise ApiError("WCL events were not ordered by timestamp across pages.")
                    previous_timestamp = timestamp
                    unknown_fields.update(unknown)
                    event_types[canonical["type"]] += 1
                    output.write(json.dumps(canonical, ensure_ascii=False, separators=(",", ":")))
                    output.write("\n")
                    sequence += 1

        return {
            "schema_version": SCHEMA_VERSION,
            "complete": True,
            "generated_at": _now(),
            "identity": {
                "report_code": index["report"]["code"],
                "report_revision": index["report"]["revision"],
                "fight_id": fight["fight_id"],
            },
            "fight": fight,
            "report_index": "../../report.json",
            "events_file": events_path.name,
            "events_sha256": sha256_file(events_path),
            "event_count": sequence,
            "event_type_counts": dict(sorted(event_types.items())),
            "unknown_fields": dict(sorted(unknown_fields.items())),
            "raw_pages": checkpoint["pages"],
            "collection": {
                "data_type": "All",
                "include_resources": True,
                "page_limit": 10_000,
                "page_count": len(checkpoint["pages"]),
            },
        }

    def _validate_report(self, report: dict[str, Any]) -> None:
        if not report:
            raise ApiError("The report does not exist or is not accessible with client credentials.")
        if report.get("visibility") not in {"public", "unlisted"}:
            raise InputError("Only public and unlisted WCL reports are supported.")
        game_version = (report.get("masterData") or {}).get("gameVersion")
        if game_version != RETAIL_GAME_VERSION:
            raise InputError(f"Only Retail reports are supported; WCL returned gameVersion={game_version!r}.")
        if not isinstance(report.get("revision"), int):
            raise ApiError("WCL did not return a numeric report revision.")
        if any(fight.get("keystoneLevel") is not None for fight in report.get("fights") or []):
            raise InputError("Mythic+ reports are unsupported; provide a Retail raid report.")
        if not _is_raid_zone(report.get("zone")):
            raise InputError("The WCL report is not identified as a Retail raid zone.")

    def _fight_summaries(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        actors = {
            actor.get("id"): actor
            for actor in (report.get("masterData") or {}).get("actors") or []
            if isinstance(actor, dict) and isinstance(actor.get("id"), int)
        }
        archive = report.get("archiveStatus") or {}
        archive_blocked = archive.get("isArchived") is True and archive.get("isAccessible") is not True
        summaries = []
        for fight in report.get("fights") or []:
            encounter_id = fight.get("encounterID")
            kind = "boss" if isinstance(encounter_id, int) and encounter_id > 0 else "trash"
            reason = None
            if kind != "boss":
                reason = "trash"
            elif fight.get("inProgress") is not False:
                reason = "in_progress" if fight.get("inProgress") is True else "completion_unknown"
            elif archive_blocked:
                reason = "archived_events_inaccessible"
            participants = []
            player_ids = fight.get("friendlyPlayers") or []
            specs = fight.get("friendlySpecs") or []
            item_levels = fight.get("friendlyItemLevels") or []
            for position, actor_id in enumerate(player_ids):
                actor = actors.get(actor_id, {})
                participants.append(
                    {
                        "actor_id": actor_id,
                        "name": actor.get("name"),
                        "server": actor.get("server"),
                        "class": actor.get("subType"),
                        "spec": specs[position] if position < len(specs) else None,
                        "item_level": item_levels[position] if position < len(item_levels) else None,
                    }
                )
            summaries.append(
                {
                    "fight_id": fight.get("id"),
                    "encounter_id": encounter_id,
                    "name": fight.get("name"),
                    "kind": kind,
                    "start_time": fight.get("startTime"),
                    "end_time": fight.get("endTime"),
                    "duration_ms": _duration(fight),
                    "kill": fight.get("kill"),
                    "in_progress": fight.get("inProgress"),
                    "difficulty": fight.get("difficulty"),
                    "size": fight.get("size"),
                    "fight_percentage": fight.get("fightPercentage"),
                    "boss_percentage": fight.get("bossPercentage"),
                    "last_phase": fight.get("lastPhase"),
                    "last_phase_absolute": fight.get("lastPhaseAsAbsoluteIndex"),
                    "last_phase_is_intermission": fight.get("lastPhaseIsIntermission"),
                    "phase_transitions": fight.get("phaseTransitions") or [],
                    "participants": participants,
                    "packable": reason is None,
                    "unpackable_reason": reason,
                }
            )
        return summaries

    def _resolve_url_fight(self, ref: ReportRef, fights: list[dict[str, Any]]) -> int | None:
        if ref.fight is None:
            return None
        if ref.fight == "last":
            if not fights:
                raise InputError(f"Report {ref.code} contains no fights.")
            return int(fights[-1]["fight_id"])
        if not any(fight["fight_id"] == ref.fight for fight in fights):
            raise InputError(f"Fight {ref.fight} is not present in report {ref.code}.")
        return ref.fight

    @staticmethod
    def _choice(fight: dict[str, Any] | None) -> dict[str, Any] | None:
        if fight is None:
            return None
        return {
            key: fight.get(key)
            for key in (
                "fight_id", "encounter_id", "name", "kill", "in_progress", "difficulty", "duration_ms",
                "fight_percentage", "boss_percentage", "packable", "unpackable_reason",
            )
        } | {"participants": len(fight.get("participants") or [])}


def query_bundle(
    manifest_path: Path,
    *,
    event_types: set[str] | None = None,
    source_id: int | None = None,
    target_id: int | None = None,
    ability_id: int | None = None,
    from_ms: float | None = None,
    to_ms: float | None = None,
    cursor: int | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    if limit <= 0 or limit > 10_000:
        raise InputError("Query limit must be between 1 and 10000.")
    manifest = read_json(manifest_path)
    if manifest.get("complete") is not True:
        raise DatasetError("Only complete Fight Bundles can be queried.")
    events_path = _validate_bundle_file(manifest_path, manifest)
    returned: list[dict[str, Any]] = []
    matched = 0
    with gzip.open(events_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            if cursor is not None and event["sequence"] <= cursor:
                continue
            if event_types and event["type"] not in event_types:
                continue
            if source_id is not None and (event.get("source") or {}).get("actor_id") != source_id:
                continue
            if target_id is not None and (event.get("target") or {}).get("actor_id") != target_id:
                continue
            if ability_id is not None and event.get("ability_id") != ability_id:
                continue
            if from_ms is not None and event["fight_time_ms"] < from_ms:
                continue
            if to_ms is not None and event["fight_time_ms"] > to_ms:
                continue
            matched += 1
            if len(returned) < limit:
                returned.append(event)
    truncated = matched > len(returned)
    return {
        "ok": True,
        "action": "query",
        "manifest_path": str(manifest_path),
        "matched": matched,
        "returned": len(returned),
        "truncated": truncated,
        "next_cursor": returned[-1]["sequence"] if truncated and returned else None,
        "events": returned,
    }


def _canonical_event(
    event: dict[str, Any], *, sequence: int, fight_start: float, page_number: int, page_index: int
) -> tuple[dict[str, Any], set[str]]:
    timestamp = event.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ApiError("A WCL event did not contain a numeric timestamp.")
    ability_id = event.get("abilityGameID")
    if ability_id is None and isinstance(event.get("ability"), dict):
        ability = event["ability"]
        ability_id = ability.get("gameID") or ability.get("guid") or ability.get("id")
    event_type = str(event.get("type") or "unknown")
    recognized = COMMON_EVENT_FIELDS | DETAIL_EVENT_FIELDS
    fields = {key: event[key] for key in sorted(DETAIL_EVENT_FIELDS) if key in event}
    unknown = set(event) - recognized
    return (
        {
            "sequence": sequence,
            "report_time_ms": timestamp,
            "fight_time_ms": timestamp - fight_start,
            "type": event_type,
            "source": _actor_ref(event, "source"),
            "target": _actor_ref(event, "target"),
            "ability_id": ability_id,
            "fields": fields,
            "raw_ref": {"page": page_number, "index": page_index},
        },
        unknown,
    )


def _actor_ref(event: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    actor_id = event.get(f"{prefix}ID")
    instance_id = event.get(f"{prefix}InstanceID", event.get(f"{prefix}Instance"))
    if actor_id is None and instance_id is None:
        return None
    return {"actor_id": actor_id, "instance_id": instance_id}


def _bundle_result(path: Path, manifest: dict[str, Any], *, cache_hit: bool) -> dict[str, Any]:
    return {
        "fight_id": manifest["identity"]["fight_id"],
        "manifest_path": str(path),
        "event_count": manifest["event_count"],
        "cache_hit": cache_hit,
    }


def _validate_bundle_file(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    events_name = manifest.get("events_file")
    if not isinstance(events_name, str):
        raise DatasetError("Fight Bundle manifest has no events file.")
    events_path = (manifest_path.parent / events_name).resolve()
    if events_path.parent != manifest_path.parent.resolve():
        raise DatasetError("Fight Bundle events file points outside the bundle directory.")
    if not events_path.is_file() or sha256_file(events_path) != manifest.get("events_sha256"):
        raise DatasetError(f"Fight Bundle event stream failed checksum validation: {events_path}")
    return events_path


def _stable_index(index: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in index.items() if key != "generated_at"}


def _is_raid_zone(zone: Any) -> bool:
    if not isinstance(zone, dict):
        return False
    difficulties = zone.get("difficulties")
    if not isinstance(difficulties, list) or not difficulties:
        return False
    for difficulty in difficulties:
        sizes = difficulty.get("sizes") if isinstance(difficulty, dict) else None
        if isinstance(sizes, list) and (not sizes or any(isinstance(size, int) and size > 5 for size in sizes)):
            return True
    return False


def _duration(fight: dict[str, Any]) -> float | None:
    start = fight.get("startTime")
    end = fight.get("endTime")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        return end - start
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
