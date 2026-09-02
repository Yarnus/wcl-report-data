from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .coach_models import CoachRequest
from .storage import artifact_lock, atomic_write_json, read_json
from .errors import InputError


class CoachTaskStore:
    """Persist request orchestration without mutating completed Guide Snapshots."""

    def __init__(self, root: Path) -> None:
        self.root = root / "tasks"

    def create_or_resume(self, request: CoachRequest, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        fingerprint = request.fingerprint(context=context)
        path = self.root / f"{fingerprint}.json"
        with artifact_lock(path):
            if path.exists():
                task = read_json(path)
                if isinstance(task, dict):
                    return task
            now = datetime.now(timezone.utc).isoformat()
            task = {
                "schema_version": 1,
                "task_id": uuid4().hex,
                "request_fingerprint": fingerprint,
                "request": request.as_dict(),
                "context": context or {},
                "status": "pending_confirmation",
                "encounters": [],
                "created_at": now,
                "updated_at": now,
            }
            atomic_write_json(path, task)
            return task

    def list_tasks(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        result = []
        for path in sorted(self.root.glob("*.json")):
            value = read_json(path)
            if isinstance(value, dict):
                result.append(value)
        return result

    def confirm(self, task_id: str) -> dict[str, Any]:
        return self._update(task_id, lambda value: value | {"status": "confirmed"}, allowed={"pending_confirmation", "confirmed"})

    def record_encounter(
        self, task_id: str, *, designator: str, status: str, artifacts: dict[str, str] | None = None, blocker: str | None = None
    ) -> dict[str, Any]:
        if status not in {"pending", "in_progress", "completed", "blocked"}:
            raise InputError("Encounter task status is invalid.")

        def update(value: dict[str, Any]) -> dict[str, Any]:
            expected = {
                item.get("value")
                for item in value.get("request", {}).get("encounter_designators", [])
                if isinstance(item, dict)
            }
            if designator not in expected:
                raise InputError(f"Encounter Designator {designator} is absent from this Coach Request.")
            if status == "completed" and (
                not artifacts or any(not Path(path).is_file() for path in artifacts.values())
            ):
                raise InputError("A completed encounter requires existing artifact files.")
            encounters = [item for item in value.get("encounters", []) if isinstance(item, dict) and item.get("designator") != designator]
            encounters.append({"designator": designator, "status": status, "artifacts": artifacts or {}, "blocker": blocker})
            completed = {item["designator"] for item in encounters if item["status"] == "completed"}
            if expected and completed == expected:
                task_status = "completed"
            elif completed:
                task_status = "partial"
            else:
                task_status = "in_progress"
            return value | {"status": task_status, "encounters": sorted(encounters, key=lambda item: item["designator"])}

        return self._update(task_id, update, allowed={"confirmed", "in_progress", "partial"})

    def _update(self, task_id: str, transform: Any, *, allowed: set[str]) -> dict[str, Any]:
        for path in self.root.glob("*.json") if self.root.exists() else ():
            with artifact_lock(path):
                value = read_json(path)
                if isinstance(value, dict) and value.get("task_id") == task_id:
                    if value.get("status") not in allowed:
                        raise InputError(f"Coach Request {task_id} cannot be updated from its current state.")
                    value = transform(value)
                    value["updated_at"] = datetime.now(timezone.utc).isoformat()
                    atomic_write_json(path, value)
                    return value
        raise InputError(f"Unknown Coach Request task_id: {task_id}.")
