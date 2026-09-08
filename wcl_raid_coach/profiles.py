from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .errors import InputError
from .storage import artifact_lock, atomic_write_json, read_json


ProfileKind = Literal["specialization", "encounter"]


def validate_profile(value: Any, expected_kind: ProfileKind | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError("Profile must be a JSON object.")
    kind = value.get("kind")
    if kind not in {"specialization", "encounter"}:
        raise InputError("Profile kind must be specialization or encounter.")
    if expected_kind is not None and kind != expected_kind:
        raise InputError(f"Expected a {expected_kind} Profile.")
    identity = value.get("identity")
    if not isinstance(identity, dict):
        raise InputError("Profile identity must be an object.")
    for field in ("game_version", "partition_id"):
        if identity.get(field) in (None, ""):
            raise InputError(f"Profile identity requires {field}.")
    if kind == "specialization":
        for field in ("class_name", "spec_name"):
            if not isinstance(identity.get(field), str) or not identity[field].strip():
                raise InputError(f"Specialization Profile identity requires {field}.")
        if not isinstance(value.get("abilities"), list):
            raise InputError("Specialization Profile abilities must be a list.")
        ability_ids = set()
        for ability in value["abilities"]:
            if not isinstance(ability, dict) or not _positive_int(ability.get("id")):
                raise InputError("Every specialization ability requires a positive numeric id.")
            if ability["id"] in ability_ids:
                raise InputError("Specialization ability IDs must be unique.")
            ability_ids.add(ability["id"])
            if "action_type" in ability and ability["action_type"] not in (
                "player_cast", "automatic", "internal", "owned_actor"
            ):
                raise InputError("Specialization ability action_type is invalid.")
            if ability.get("action_type") == "player_cast" and ability["id"] == 1:
                raise InputError("WCL synthetic Melee ID 1 cannot be declared a player_cast.")
        for field in ("resources", "cooldown_relationships", "role_guardrails"):
            if not isinstance(value.get(field), list) or not value[field]:
                raise InputError(f"Specialization Profile requires non-empty {field}.")
    else:
        for field in ("encounter_id", "difficulty_id"):
            if not _positive_int(identity.get(field)):
                raise InputError(f"Encounter Profile identity requires a positive {field}.")
        eligibility = value.get("eligibility")
        if not isinstance(eligibility, dict):
            raise InputError("Encounter Profile requires eligibility rules.")
        if not isinstance(eligibility.get("priority_target_ids"), list):
            raise InputError("Encounter Profile eligibility requires priority_target_ids.")
        if not isinstance(eligibility.get("excluded_target_ids"), list):
            raise InputError("Encounter Profile eligibility requires excluded_target_ids.")
        target_ids = eligibility["priority_target_ids"] + eligibility["excluded_target_ids"]
        if (target_ids or "target_id_type" in eligibility) and eligibility.get("target_id_type") != "npc_game_id":
            raise InputError("Encounter Profile target IDs require target_id_type npc_game_id; report-local actor IDs are not comparable.")
        if any(not _positive_int(item) for item in target_ids) or len(set(target_ids)) != len(target_ids):
            raise InputError("Encounter Profile target IDs must be distinct positive NPC gameIDs across both lists.")
        for field in ("phases", "mechanic_anchors"):
            if not isinstance(value.get(field), list) or not value[field]:
                raise InputError(f"Encounter Profile requires non-empty {field}.")
        for anchor in value["mechanic_anchors"]:
            if (
                not isinstance(anchor, dict)
                or not _positive_int(anchor.get("ability_id"))
                or not isinstance(anchor.get("name"), str)
                or not anchor["name"].strip()
            ):
                raise InputError("Every encounter mechanic anchor requires a positive ability ID and name.")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise InputError("Profile requires at least one sourced assertion.")
    for source in sources:
        if not isinstance(source, dict):
            raise InputError("Profile source must be an object.")
        for field in ("url", "title", "accessed_at", "quote_summary", "content_hash"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise InputError(f"Profile source requires {field}.")
        if re.fullmatch(r"[0-9a-fA-F]{64}", source["content_hash"]) is None:
            raise InputError("Profile source content_hash must be a SHA-256 hex digest.")
        try:
            datetime.fromisoformat(source["accessed_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise InputError("Profile source accessed_at must be ISO 8601.") from exc
    declared_id = value.get("profile_id")
    if declared_id is not None and (
        not isinstance(declared_id, str) or not re.fullmatch(r"[0-9a-f]{64}", declared_id)
    ):
        raise InputError("Profile profile_id must be a SHA-256 hex digest.")
    canonical = dict(value)
    canonical.pop("profile_id", None)
    profile_id = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if declared_id is not None and declared_id != profile_id:
        raise InputError("Profile profile_id does not match its canonical content.")
    return canonical | {"profile_id": profile_id}


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = root / "profiles"

    def store(self, value: Any) -> Path:
        profile = validate_profile(value)
        path = self.root / profile["kind"] / f"{profile['profile_id']}.json"
        with artifact_lock(path):
            return atomic_write_json(path, profile)

    def load(self, path: Path, expected_kind: ProfileKind | None = None) -> dict[str, Any]:
        return validate_profile(read_json(path), expected_kind)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
