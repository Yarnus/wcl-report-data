from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from .coach_models import specialization_role
from .cohort import (
    build_benchmark,
    identify_benchmark,
    qualify_reference_samples,
    REFERENCE_SAMPLE_MAX,
    validate_analysis_membership,
    verify_benchmark,
    verify_benchmark_for_cohort,
    verify_cohort,
)
from .comparison import verify_analysis_evidence
from .errors import InputError
from .profiles import validate_profile
from .report_documents import validate_rendered_report_index
from .storage import artifact_lock, atomic_write_json


REFERENCE_SAMPLE_TARGET = 3
FIRST_DELIVERY_TARGET_SECONDS = 180.0
REUSE_TARGET_SECONDS = 30.0
VALIDATION_RENDER_RESERVE_SECONDS = 20.0
CLOCK_BASELINE_TOLERANCE_SECONDS = 1.0
STAGE_NAMES = {
    "selection", "player_evidence", "benchmark_reuse", "reference_validation",
    "benchmark_build",
}
PROGRESS_STAGES = {"retrieval", "agent_synthesis", "validation", "rendering"}
BLOCKERS = {
    "budget_exhausted", "comparison_unavailable", "player_evidence_incomplete",
    "profile_unavailable", "ranking_page_exhausted", "ranking_cohort_refresh_required",
    "timing_continuity_unavailable", "wcl_api_failure", "wcl_rate_limit",
}
EXTERNAL_BLOCKERS = {"wcl_api_failure", "wcl_rate_limit"}
REJECTION_REASONS = {
    "duplicate_identity", "excluded_target_damage_dominates", "hard_condition_mismatch",
    "incomplete_identity", "malformed_analysis", "malformed_candidate",
    "missing_complete_bundle_provenance", "missing_healing_evidence", "missing_target_damage",
    "no_priority_target_damage", "outside_recent_window", "player_death",
    "source_identity_not_unique", "unsupported_analysis_schema",
}
HARD_CONDITION_FIELDS = (
    "game_version", "partition_id", "encounter_id", "difficulty_id", "class_name", "spec_name",
)


def initialize_personal_review(
    report_code: str,
    fight_id: int,
    actor_id: int,
    output_dir: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    started = clock()
    invocation_wall = wall_clock()
    baseline = invocation_wall - started
    if (
        not isinstance(report_code, str)
        or not report_code.isalnum()
        or type(fight_id) is not int
        or fight_id <= 0
        or type(actor_id) is not int
        or actor_id <= 0
        or not _nonnegative(started)
        or not _finite(invocation_wall)
        or not _finite(baseline)
    ):
        raise InputError("Personal Review selected identity is invalid.")
    measured_at, measured_baseline = _clock_sample(clock, wall_clock)
    continuity_available = (
        measured_at >= started
        and abs(measured_baseline - baseline) <= CLOCK_BASELINE_TOLERANCE_SECONDS
    )
    result = {
        "schema_version": 2,
        "artifact_type": "personal_review_workflow",
        "selected_identity": {
            "report_code": report_code,
            "fight_id": fight_id,
            "actor_id": actor_id,
        },
        "workflow_started_monotonic_seconds": started,
        "clock": {
            "wall_minus_monotonic_seconds": baseline,
            "session_marker": _clock_session_marker(invocation_wall, started),
            "baseline_tolerance_seconds": CLOCK_BASELINE_TOLERANCE_SECONDS,
            "continuity_available": continuity_available,
            "clock_source": _clock_source(clock, wall_clock),
        },
        "completion_state": "blocked",
        "report_available": False,
        "player_evidence_complete": False,
        "comparison_available": False,
        "reference_sample_target": REFERENCE_SAMPLE_TARGET,
        "qualified_reference_samples": 0,
        "candidate_progress": [],
        "next_ranking_candidate": None,
        "blockers": ["player_evidence_incomplete", "profile_unavailable", "comparison_unavailable"],
        "budget": {
            "target_seconds": FIRST_DELIVERY_TARGET_SECONDS,
            "elapsed_seconds": measured_at - started,
            "validation_render_reserve_seconds": VALIDATION_RENDER_RESERVE_SECONDS,
            "optional_acquisition_open": (
                continuity_available
                and measured_at - started < FIRST_DELIVERY_TARGET_SECONDS - VALIDATION_RENDER_RESERVE_SECONDS
            ),
            "kind": "measured_soft_target",
        },
        "stage_timings_seconds": {"selection": 0.0},
        "stage_progress": {
            "retrieval": "in_progress",
            "agent_synthesis": "unavailable",
            "validation": "pending",
            "rendering": "pending",
        },
        "artifacts": {
            "requested_personal_analysis_path": None,
            "personal_analysis": None,
            "ranking_cohort": None,
            "encounter_profile": None,
            "specialization_profile": None,
            "reference_analyses": [],
            "benchmark_reference_evidence": [],
            "encounter_benchmark": None,
            "previous_workflow": None,
            "progress": [],
        },
        "benchmark_reused": False,
    }
    verify_personal_workflow(result, require_id=False)
    persisted = _persist_result(output_dir.expanduser().resolve(), result)
    return persisted | {
        "invocation_timing": _workflow_invocation_timing(
            persisted, started, baseline, FIRST_DELIVERY_TARGET_SECONDS, clock, wall_clock
        )
    }


def orchestrate_personal_review(
    analysis_path: Path,
    cohort_path: Path,
    encounter_profile_path: Path,
    specialization_profile_path: Path,
    output_dir: Path,
    *,
    reference_analysis_paths: list[Path],
    benchmark_paths: list[Path],
    candidate_rejections: list[tuple[str, str]],
    blockers: list[str],
    previous_workflow_path: Path,
    progress_paths: list[Path] | None = None,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    invocation_started = clock()
    invocation_wall = wall_clock()
    started = invocation_started
    baseline = invocation_wall - invocation_started
    session_marker = _clock_session_marker(invocation_wall, invocation_started)
    stages: dict[str, float] = {}
    if not _nonnegative(started) or not _finite(invocation_wall) or not _finite(baseline) or set(blockers) - EXTERNAL_BLOCKERS:
        raise InputError("Personal Review blocker is unsupported.")

    analysis_path = analysis_path.expanduser().resolve()
    cohort_path = cohort_path.expanduser().resolve()
    encounter_profile_path = encounter_profile_path.expanduser().resolve()
    specialization_profile_path = specialization_profile_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()

    cohort_snapshot = _timed(stages, "selection", clock, lambda: _read_snapshot(cohort_path, "Ranking Cohort"))
    cohort, cohort_ref = cohort_snapshot
    verify_cohort(cohort)
    candidates = _cohort_candidates(cohort)
    filters = _object(cohort.get("filters"), "Ranking Cohort filters")
    expected = {field: filters.get(field) for field in HARD_CONDITION_FIELDS}
    if any(value is None for value in expected.values()):
        raise InputError("Ranking Cohort hard-condition filters are incomplete.")

    previous, previous_ref = _load_previous(previous_workflow_path, cohort_ref, output_dir)
    previous_started = previous["workflow_started_monotonic_seconds"]
    previous_clock = _object(previous.get("clock"), "Personal Review workflow clock")
    previous_baseline = previous_clock.get("wall_minus_monotonic_seconds")
    if (
        previous_clock.get("continuity_available") is not True
        or previous_clock.get("session_marker") != _clock_session_marker(
            invocation_wall, invocation_started
        )
        or previous_started > invocation_started
        or not _finite(previous_baseline)
        or abs(previous_baseline - baseline) > CLOCK_BASELINE_TOLERANCE_SECONDS
    ):
        blockers = blockers + ["timing_continuity_unavailable"]
    else:
        started = previous_started
        baseline = previous_baseline
        current_stages = stages
        stages = dict(previous["stage_timings_seconds"])
        for name, duration in current_stages.items():
            stages[name] = stages.get(name, 0.0) + duration
    reference_paths = _merge_reference_paths(previous, reference_analysis_paths)
    if previous:
        previous_benchmark = (previous.get("artifacts") or {}).get("encounter_benchmark")
        if previous_benchmark:
            benchmark_paths = _merge_artifact_path(previous_benchmark, benchmark_paths, "Encounter Benchmark")
    progress_refs = _merge_progress_refs(previous, progress_paths or [])
    rejection_map = _previous_rejections(previous)
    for candidate_id in rejection_map:
        _candidate_by_id(candidates, candidate_id)
    for candidate_id, reason in candidate_rejections:
        if reason not in REJECTION_REASONS:
            raise InputError("Personal Review candidate rejection reason is unsupported.")
        _candidate_by_id(candidates, candidate_id)
        rejection_map[candidate_id] = reason

    encounter_profile, encounter_profile_ref = _optional_profile(encounter_profile_path, "encounter")
    specialization_profile, specialization_profile_ref = _optional_profile(specialization_profile_path, "specialization")
    profiles_complete = encounter_profile is not None and specialization_profile is not None
    if profiles_complete:
        _verify_profile_identity(encounter_profile, specialization_profile, expected)
    elif "profile_unavailable" not in blockers:
        blockers = blockers + ["profile_unavailable"]

    analysis, analysis_ref = _optional_analysis(analysis_path)
    player_evidence_complete = analysis is not None
    if analysis is not None:
        _timed(stages, "player_evidence", clock, lambda: verify_analysis_evidence(analysis))
        _verify_selected_analysis_identity(analysis, previous["selected_identity"])
        analysis_identity = _object(analysis.get("comparison_identity"), "Personal Analysis comparison identity")
        if any(analysis_identity.get(field) != expected.get(field) for field in analysis_identity):
            raise InputError("Personal Analysis does not match the current Ranking Cohort.")
    elif "player_evidence_incomplete" not in blockers:
        blockers = blockers + ["player_evidence_incomplete"]

    benchmark = None
    benchmark_path = None
    benchmark_ref = None
    benchmark_reused = False
    if profiles_complete:
        for path in benchmark_paths:
            path = path.expanduser().resolve()
            with artifact_lock(path):
                value, value_ref = _read_snapshot(path, "Encounter Benchmark")
                verify_benchmark(value)
                if (
                    value.get("cohort_id") != cohort["cohort_id"]
                    or value.get("identity") != expected
                    or value.get("encounter_profile_id") != encounter_profile["profile_id"]
                    or value.get("specialization_profile_id") != specialization_profile["profile_id"]
                    or value.get("sources") != {
                        "encounter": encounter_profile["sources"],
                        "specialization": specialization_profile["sources"],
                    }
                ):
                    continue
                _timed(
                    stages,
                    "benchmark_reuse",
                    clock,
                    lambda value=value: verify_benchmark_for_cohort(
                        value, cohort, encounter_profile, specialization_profile
                    ),
                )
                if _snapshot_ref(path) != value_ref:
                    raise InputError("Encounter Benchmark changed during workflow validation.")
                benchmark, benchmark_path, benchmark_ref = value, path, value_ref
                benchmark_reused = True
                break

    budget = REUSE_TARGET_SECONDS if benchmark is not None else FIRST_DELIVERY_TARGET_SECONDS
    accepted: list[dict[str, Any]] = []
    eligibility_rejections: list[dict[str, Any]] = []
    analyses: list[dict[str, Any]] = []
    reference_refs = [_snapshot_ref(path) for path in reference_paths]
    if benchmark is None and profiles_complete and reference_paths:
        def validate_references() -> None:
            nonlocal analyses, accepted, eligibility_rejections
            snapshots = [_read_snapshot(path, "Reference Sample analysis") for path in reference_paths]
            analyses = [value for value, _ in snapshots]
            if [ref for _, ref in snapshots] != reference_refs:
                raise InputError("Reference Sample analysis changed during workflow validation.")
            validate_analysis_membership(analyses, cohort)
            priority = {str(value) for value in encounter_profile["eligibility"]["priority_target_ids"]}
            excluded = {str(value) for value in encounter_profile["eligibility"]["excluded_target_ids"]}
            accepted, eligibility_rejections = qualify_reference_samples(
                analyses, expected, priority, excluded,
                specialization_role(str(expected.get("class_name")), str(expected.get("spec_name"))),
            )

        _timed(stages, "reference_validation", clock, validate_references)
        rejection_by_sample = {item["sample"]: item["reason"] for item in eligibility_rejections}
        for index, analysis_value in enumerate(analyses, 1):
            candidate_id = _analysis_candidate_id(analysis_value)
            _candidate_by_id(candidates, candidate_id)
            reason = rejection_by_sample.get(index)
            if reason:
                rejection_map[candidate_id] = reason

    if benchmark is None and len(accepted) >= REFERENCE_SAMPLE_TARGET:
        def create_benchmark() -> tuple[dict[str, Any], Path, dict[str, str]]:
            value = identify_benchmark(build_benchmark(
                analyses, encounter_profile, specialization_profile, expected,
                cohort_id=cohort["cohort_id"],
            ))
            path = output_dir / "benchmarks" / f'{value["benchmark_id"]}.json'
            expected_bytes = _json_file_bytes(value)
            with artifact_lock(path):
                if path.exists():
                    payload = path.read_bytes()
                    if payload != expected_bytes:
                        raise InputError("Existing Encounter Benchmark has an invalid identity.")
                else:
                    atomic_write_json(path, value)
                    payload = path.read_bytes()
                    if payload != expected_bytes:
                        raise InputError("Persisted Encounter Benchmark does not match its validated content.")
                ref = {"path": str(path.resolve()), "sha256": hashlib.sha256(payload).hexdigest()}
            return value, path, ref

        benchmark, benchmark_path, benchmark_ref = _timed(stages, "benchmark_build", clock, create_benchmark)

    for value in accepted:
        rejection_map.pop(_analysis_candidate_id(value), None)
    processed = set(rejection_map) | {_analysis_candidate_id(value) for value in analyses}
    next_candidate = next((item for item in candidates if _candidate_id(item) not in processed), None)
    measured_at, measured_baseline = _clock_sample(clock, wall_clock)
    continuity_available = (
        "timing_continuity_unavailable" not in blockers
        and measured_at >= started
        and abs(measured_baseline - baseline) <= CLOCK_BASELINE_TOLERANCE_SECONDS
    )
    if not continuity_available:
        blockers = blockers + ["timing_continuity_unavailable"]
    elapsed = measured_at - started if continuity_available else measured_at - invocation_started
    optional_open = continuity_available and elapsed < budget - VALIDATION_RENDER_RESERVE_SECONDS
    exhausted = (cohort.get("pagination") or {}).get("exhausted") is True
    generated_blockers = list(blockers)
    if not optional_open and benchmark is None:
        generated_blockers.append("budget_exhausted")
    if next_candidate is None and benchmark is None:
        generated_blockers.append("ranking_page_exhausted" if exhausted else "ranking_cohort_refresh_required")
    if (benchmark is None or not player_evidence_complete) and (not optional_open or blockers or next_candidate is None or not player_evidence_complete):
        generated_blockers.append("comparison_unavailable")

    report_available = player_evidence_complete and profiles_complete
    if not report_available:
        state = "blocked"
        next_candidate = None
    elif benchmark is not None:
        state = "comparison_ready"
        next_candidate = None
    elif not optional_open or blockers or next_candidate is None:
        state = "partial_ready"
        next_candidate = None
    else:
        state = "acquiring"

    result = {
        "schema_version": 2,
        "artifact_type": "personal_review_workflow",
        "selected_identity": previous["selected_identity"],
        "workflow_started_monotonic_seconds": started,
        "clock": {
            "wall_minus_monotonic_seconds": baseline,
            "session_marker": session_marker,
            "baseline_tolerance_seconds": CLOCK_BASELINE_TOLERANCE_SECONDS,
            "continuity_available": continuity_available,
            "clock_source": _clock_source(clock, wall_clock),
        },
        "completion_state": state,
        "report_available": report_available,
        "player_evidence_complete": player_evidence_complete,
        "comparison_available": benchmark is not None and player_evidence_complete,
        "reference_sample_target": REFERENCE_SAMPLE_TARGET,
        "qualified_reference_samples": benchmark.get("sample_count", len(accepted)) if benchmark else len(accepted),
        "candidate_progress": _candidate_progress(candidates, analyses, rejection_map),
        "next_ranking_candidate": next_candidate,
        "blockers": list(dict.fromkeys(generated_blockers)),
        "budget": {
            "target_seconds": budget,
            "elapsed_seconds": elapsed,
            "validation_render_reserve_seconds": VALIDATION_RENDER_RESERVE_SECONDS,
            "optional_acquisition_open": optional_open,
            "kind": "measured_soft_target",
        },
        "stage_timings_seconds": dict(sorted(stages.items())),
        "stage_progress": {
            "retrieval": "completed" if report_available and state != "acquiring" else "in_progress",
            "agent_synthesis": "in_progress" if report_available else "unavailable",
            "validation": "pending",
            "rendering": "pending",
        },
        "artifacts": {
            "requested_personal_analysis_path": str(analysis_path),
            "personal_analysis": analysis_ref if player_evidence_complete else None,
            "ranking_cohort": cohort_ref,
            "encounter_profile": encounter_profile_ref,
            "specialization_profile": specialization_profile_ref,
            "reference_analyses": reference_refs,
            "benchmark_reference_evidence": (
                _benchmark_reference_evidence(benchmark) if benchmark is not None else []
            ),
            "encounter_benchmark": benchmark_ref,
            "previous_workflow": previous_ref,
            "progress": progress_refs,
        },
        "benchmark_reused": benchmark_reused,
    }
    verify_personal_workflow(result, require_id=False)
    input_refs = [
        ref for ref in (
            analysis_ref, cohort_ref, encounter_profile_ref, specialization_profile_ref,
            benchmark_ref, previous_ref, *reference_refs, *progress_refs,
            *(
                evidence_ref
                for item in result["artifacts"]["benchmark_reference_evidence"]
                for evidence_ref in (item["manifest"], item["index"])
            ),
        ) if ref is not None
    ]
    _verify_refs_current(input_refs)
    persisted = _persist_result(output_dir, result)
    invocation_timing = _workflow_invocation_timing(
        persisted, started, baseline, budget, clock, wall_clock
    )
    return persisted | {"invocation_timing": invocation_timing}


def verify_personal_workflow(value: Any, *, require_id: bool = True) -> dict[str, Any]:
    workflow = _object(value, "Personal Review workflow")
    if workflow.get("schema_version") != 2 or workflow.get("artifact_type") != "personal_review_workflow":
        raise InputError("Personal Review workflow uses an unsupported schema version.")
    body = dict(workflow)
    workflow_id = body.pop("workflow_id", None)
    if (require_id and workflow_id is None) or (workflow_id is not None and workflow_id != _content_id(body)):
        raise InputError("Personal Review workflow content ID is invalid.")
    stages = workflow.get("stage_timings_seconds")
    budget = workflow.get("budget")
    artifacts = workflow.get("artifacts")
    clock_state = workflow.get("clock")
    stage_progress = workflow.get("stage_progress")
    _verify_selected_identity(workflow.get("selected_identity"))
    if (
        not isinstance(stages, dict)
        or "selection" not in stages
        or set(stages) - STAGE_NAMES
        or any(not _nonnegative(item) for item in stages.values())
        or not isinstance(budget, dict)
        or not isinstance(artifacts, dict)
        or not isinstance(clock_state, dict)
        or not isinstance(stage_progress, dict)
        or set(stage_progress) != PROGRESS_STAGES
        or any(not isinstance(status, str) or status not in ("pending", "in_progress", "completed", "unavailable") for status in stage_progress.values())
        or not _nonnegative(workflow.get("workflow_started_monotonic_seconds"))
        or not _finite(clock_state.get("wall_minus_monotonic_seconds"))
        or not isinstance(clock_state.get("session_marker"), str)
        or len(clock_state["session_marker"]) != 16
        or clock_state.get("baseline_tolerance_seconds") != CLOCK_BASELINE_TOLERANCE_SECONDS
        or type(clock_state.get("continuity_available")) is not bool
        or not _nonnegative(budget.get("elapsed_seconds"))
        or budget.get("target_seconds") not in (FIRST_DELIVERY_TARGET_SECONDS, REUSE_TARGET_SECONDS)
        or budget.get("validation_render_reserve_seconds") != VALIDATION_RENDER_RESERVE_SECONDS
        or budget.get("kind") != "measured_soft_target"
        or type(budget.get("optional_acquisition_open")) is not bool
        or budget["optional_acquisition_open"]
        != (
            clock_state["continuity_available"]
            and budget["elapsed_seconds"] < budget["target_seconds"] - VALIDATION_RENDER_RESERVE_SECONDS
        )
        or sum(stages.values()) > budget["elapsed_seconds"] + 1e-9
    ):
        raise InputError("Personal Review workflow timing data is invalid.")
    if workflow.get("benchmark_reused") is True and budget["target_seconds"] != REUSE_TARGET_SECONDS:
        raise InputError("Personal Review workflow reuse budget is invalid.")
    if workflow.get("benchmark_reused") is not True and budget["target_seconds"] != FIRST_DELIVERY_TARGET_SECONDS:
        raise InputError("Personal Review workflow first-delivery budget is invalid.")
    if type(workflow.get("benchmark_reused")) is not bool:
        raise InputError("Personal Review workflow Benchmark reuse state is invalid.")
    if stage_progress["agent_synthesis"] not in ("in_progress", "unavailable") or stage_progress["validation"] != "pending" or stage_progress["rendering"] != "pending":
        raise InputError("Personal Review workflow stage progress is invalid.")
    if workflow.get("player_evidence_complete") is True and "player_evidence" not in stages:
        raise InputError("Personal Review workflow player evidence timing is missing.")
    if workflow.get("benchmark_reused") is True and "benchmark_reuse" not in stages:
        raise InputError("Personal Review workflow Benchmark reuse timing is missing.")
    if not isinstance(workflow.get("completion_state"), str) or workflow.get("completion_state") not in ("acquiring", "comparison_ready", "partial_ready", "blocked"):
        raise InputError("Personal Review workflow completion state is invalid.")
    if not isinstance(workflow.get("blockers"), list) or any(
        not isinstance(item, str) or item not in BLOCKERS for item in workflow["blockers"]
    ):
        raise InputError("Personal Review workflow blockers are invalid.")
    if (
        type(workflow.get("report_available")) is not bool
        or type(workflow.get("player_evidence_complete")) is not bool
        or type(workflow.get("comparison_available")) is not bool
        or workflow.get("reference_sample_target") != REFERENCE_SAMPLE_TARGET
    ):
        raise InputError("Personal Review workflow availability state is invalid.")
    count = workflow.get("qualified_reference_samples")
    progress = workflow.get("candidate_progress")
    if type(count) is not int or not 0 <= count <= REFERENCE_SAMPLE_MAX or not isinstance(progress, list):
        raise InputError("Personal Review workflow Reference Sample progress is invalid.")
    for item in progress:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("candidate_id"), str)
            or item.get("status") not in ("qualified", "rejected")
        ):
            raise InputError("Personal Review workflow candidate progress is invalid.")
        if item["status"] == "rejected" and (
            not isinstance(item.get("reason"), str) or item.get("reason") not in REJECTION_REASONS
        ):
            raise InputError("Personal Review workflow candidate rejection is invalid.")
    candidate = workflow.get("next_ranking_candidate")
    if candidate is not None:
        if not isinstance(candidate, dict):
            raise InputError("Personal Review workflow next Ranking Candidate is invalid.")
        _candidate_id(candidate)
    _verify_workflow_artifacts(artifacts)
    return workflow


def validate_partial_workflow(
    workflow_path: Path,
    analysis_path: Path,
    encounter_profile_path: Path,
    specialization_profile_path: Path,
    workflow_registry_dir: Path,
) -> int:
    workflow_path = workflow_path.expanduser().resolve()
    workflow, _ = _read_snapshot(workflow_path, "Personal Review workflow")
    workflow = verify_personal_workflow(workflow)
    _verify_registered_workflow(workflow_path, workflow, registry_dir=workflow_registry_dir)
    if (
        workflow.get("completion_state") != "partial_ready"
        or workflow.get("comparison_available") is not False
        or workflow.get("report_available") is not True
        or workflow.get("player_evidence_complete") is not True
    ):
        raise InputError("Personal Review workflow is not eligible for a partial report.")
    artifacts = _object(workflow.get("artifacts"), "Personal Review workflow artifacts")
    paths = {
        "personal_analysis": analysis_path.expanduser().resolve(),
        "encounter_profile": encounter_profile_path.expanduser().resolve(),
        "specialization_profile": specialization_profile_path.expanduser().resolve(),
    }
    source_values = {}
    for kind, path in paths.items():
        source_values[kind], ref = _read_snapshot(path, f"Partial Personal Review {kind}")
        if artifacts.get(kind) != ref:
            raise InputError("Partial Personal Review source does not match its workflow artifact.")
    analysis = source_values["personal_analysis"]
    verify_analysis_evidence(analysis)
    encounter = validate_profile(source_values["encounter_profile"], "encounter")
    specialization = validate_profile(source_values["specialization_profile"], "specialization")
    cohort_ref = _object(artifacts.get("ranking_cohort"), "Personal Review workflow Ranking Cohort")
    cohort_path = Path(str(cohort_ref.get("path")))
    cohort, current_cohort_ref = _read_snapshot(cohort_path, "Ranking Cohort")
    if cohort_ref != current_cohort_ref:
        raise InputError("Personal Review workflow Ranking Cohort hash is invalid.")
    verify_cohort(cohort)
    references = []
    for ref in artifacts.get("reference_analyses", []):
        ref = _object(ref, "Personal Review workflow Reference Sample")
        path = Path(str(ref.get("path")))
        analysis_value, current_ref = _read_snapshot(path, "Reference Sample analysis")
        if ref != current_ref:
            raise InputError("Personal Review workflow Reference Sample hash is invalid.")
        references.append(analysis_value)
    validate_analysis_membership(references, cohort)
    identity = _object(analysis.get("comparison_identity"), "Personal Analysis comparison identity")
    filters = _object(cohort.get("filters"), "Ranking Cohort filters")
    if any(identity.get(field) != filters.get(field) for field in HARD_CONDITION_FIELDS):
        raise InputError("Partial Personal Review Analysis does not match its Ranking Cohort.")
    _verify_profile_identity(encounter, specialization, identity)
    accepted, _ = qualify_reference_samples(
        references,
        identity,
        {str(value) for value in encounter["eligibility"]["priority_target_ids"]},
        {str(value) for value in encounter["eligibility"]["excluded_target_ids"]},
        specialization_role(str(identity.get("class_name")), str(identity.get("spec_name"))),
    )
    count = len(accepted)
    if count >= REFERENCE_SAMPLE_TARGET or workflow.get("qualified_reference_samples") != count:
        raise InputError("Personal Review workflow qualified Reference Sample count is invalid.")
    return count


def validate_comparison_workflow(
    workflow_path: Path,
    analysis_path: Path,
    benchmark_path: Path,
    workflow_registry_dir: Path,
) -> dict[str, Any]:
    workflow_path = workflow_path.expanduser().resolve()
    with artifact_lock(workflow_path):
        workflow, workflow_ref = _read_snapshot(workflow_path, "Personal Review workflow")
    workflow = verify_personal_workflow(workflow)
    _verify_registered_workflow(
        workflow_path, workflow, workflow_ref, registry_dir=workflow_registry_dir
    )
    if (
        workflow.get("completion_state") != "comparison_ready"
        or workflow.get("comparison_available") is not True
        or workflow.get("report_available") is not True
        or workflow.get("player_evidence_complete") is not True
    ):
        raise InputError("Full Personal Review requires a comparison-ready workflow.")

    artifacts = _object(workflow.get("artifacts"), "Personal Review workflow artifacts")
    paths = {
        "personal_analysis": analysis_path.expanduser().resolve(),
        "encounter_benchmark": benchmark_path.expanduser().resolve(),
    }
    refs = [workflow_ref]
    values: dict[str, dict[str, Any]] = {}
    for kind, path in paths.items():
        values[kind], ref = _read_locked_snapshot(path, f"Full Personal Review {kind}")
        if artifacts.get(kind) != ref:
            raise InputError(f"Full Personal Review {kind} does not match its workflow artifact.")
        refs.append(ref)

    for kind, label in (
        ("ranking_cohort", "Ranking Cohort"),
        ("encounter_profile", "Encounter Profile"),
        ("specialization_profile", "Specialization Profile"),
    ):
        expected_ref = _object(artifacts.get(kind), f"Personal Review workflow {label}")
        path = Path(str(expected_ref.get("path")))
        values[kind], current_ref = _read_locked_snapshot(path, label)
        if current_ref != expected_ref:
            raise InputError(f"Personal Review workflow {label} hash is invalid.")
        refs.append(current_ref)

    cohort = values["ranking_cohort"]
    encounter = validate_profile(values["encounter_profile"], "encounter")
    specialization = validate_profile(values["specialization_profile"], "specialization")
    benchmark = values["encounter_benchmark"]
    evidence_refs = _benchmark_reference_evidence(benchmark)
    if artifacts.get("benchmark_reference_evidence") != evidence_refs:
        raise InputError("Personal Review workflow Benchmark Reference Sample provenance is invalid.")
    refs.extend(
        evidence_ref
        for item in evidence_refs
        for evidence_ref in (item["manifest"], item["index"])
    )
    _verify_refs_current(refs[1:])
    verify_benchmark_for_cohort(benchmark, cohort, encounter, specialization)
    _verify_refs_current(refs)
    return workflow


def finalize_personal_review_delivery(
    workflow_path: Path,
    report: dict[str, Any],
    output_dir: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    workflow_path = workflow_path.expanduser().resolve()
    workflow, workflow_ref = _read_snapshot(workflow_path, "Personal Review workflow")
    workflow = verify_personal_workflow(workflow)
    if workflow_path.parent != (output_dir.expanduser().resolve() / "personal-workflows"):
        raise InputError("Personal Review delivery requires the canonical registered workflow artifact.")
    _verify_registered_workflow(workflow_path, workflow, workflow_ref)
    if workflow.get("report_available") is not True:
        raise InputError("Personal Review workflow is not eligible for delivery.")

    try:
        html_path = Path(report["html_path"]).expanduser().resolve()
        index_path = Path(report["index_path"]).expanduser().resolve()
        document_id = report["document_id"]
        claimed_html_sha256 = report["html_sha256"]
    except (KeyError, TypeError) as exc:
        raise InputError("Personal Review delivery report is incomplete.") from exc
    try:
        html_bytes = html_path.read_bytes()
    except OSError as exc:
        raise InputError("Personal Review HTML is missing or unreadable.") from exc
    html_ref = {
        "path": str(html_path),
        "sha256": hashlib.sha256(html_bytes).hexdigest(),
    }
    if html_ref["sha256"] != claimed_html_sha256:
        raise InputError("Personal Review HTML hash does not match the rendered report.")
    index, index_ref = _read_snapshot(index_path, "Personal Review report index")
    validated_report = validate_rendered_report_index(
        index, html_bytes, html_path.name,
        output_dir.expanduser().resolve() / "personal-workflows",
    )
    document = validated_report["document"]
    workflow_source = next(
        (
            item for item in document.get("source_artifacts", [])
            if isinstance(item, dict) and item.get("kind") == "personal_review_workflow"
        ),
        None,
    ) if isinstance(document, dict) else None
    if (
        validated_report["document_id"] != document_id
        or validated_report["document_schema_version"] != report.get("document_schema_version")
        or validated_report["renderer_schema_version"] != report.get("renderer_schema_version")
        or validated_report["html_sha256"] != claimed_html_sha256
        or index_path != html_path.with_suffix(".json")
        or workflow_source != {"kind": "personal_review_workflow", **workflow_ref}
    ):
        raise InputError("Personal Review delivery artifacts do not match the workflow and report.")
    comparison_available = document.get("comparison", {}).get("status") != "unavailable"
    if comparison_available:
        sources = {
            item.get("kind"): Path(str(item.get("path")))
            for item in document.get("source_artifacts", [])
            if isinstance(item, dict)
        }
        try:
            validate_comparison_workflow(
                workflow_path, sources["personal_analysis"], sources["encounter_benchmark"],
                output_dir.expanduser().resolve() / "personal-workflows",
            )
        except KeyError as exc:
            raise InputError("Personal Review delivery comparison sources are incomplete.") from exc
    else:
        sources = {
            item.get("kind"): Path(str(item.get("path")))
            for item in document.get("source_artifacts", [])
            if isinstance(item, dict)
        }
        try:
            validate_partial_workflow(
                workflow_path,
                sources["personal_analysis"],
                sources["encounter_profile"],
                sources["specialization_profile"],
                output_dir.expanduser().resolve() / "personal-workflows",
            )
        except KeyError as exc:
            raise InputError("Personal Review delivery partial sources are incomplete.") from exc

    _verify_refs_current([html_ref, index_ref])
    completed, current_baseline = _clock_sample(clock, wall_clock)
    session_marker = _clock_session_marker_from_baseline(current_baseline)
    clock_state = _object(workflow.get("clock"), "Personal Review workflow clock")
    started = workflow.get("workflow_started_monotonic_seconds")
    baseline = clock_state.get("wall_minus_monotonic_seconds")
    continuity = (
        clock_state.get("continuity_available") is True
        and "timing_continuity_unavailable" not in workflow.get("blockers", [])
        and _nonnegative(started)
        and _finite(baseline)
        and completed >= started
        and abs(current_baseline - baseline) <= CLOCK_BASELINE_TOLERANCE_SECONDS
        and session_marker == clock_state.get("session_marker")
    )
    target = workflow["budget"]["target_seconds"]
    elapsed = completed - started if continuity else None
    body = {
        "schema_version": 1,
        "artifact_type": "personal_review_delivery",
        "status": "delivered" if continuity else "delivered_timing_unavailable",
        "completion_status": workflow["completion_state"],
        "workflow": workflow_ref,
        "report": {
            "document_id": document_id,
            "index": index_ref,
            "html": html_ref,
        },
        "timing": {
            "elapsed_seconds": elapsed,
            "target_seconds": target,
            "target_met": None,
            "continuity_available": continuity,
            "clock_source": _clock_source(clock, wall_clock),
            "wcl_network_measurement": "not_measured",
            "measured_through": "rendered_html_and_index_verified",
            "excluded_tail": ["delivery_artifact_write", "finalization_record_write", "stdout_serialization"],
        },
        "stage_progress": {
            "retrieval": "completed",
            "agent_synthesis": "unavailable",
            "validation": "completed",
            "rendering": "completed",
        },
        "target_assessment": "unavailable_unmeasured_agent_synthesis",
    }
    persisted = _persist_content_artifact(
        output_dir.expanduser().resolve() / "personal-deliveries",
        body,
        "delivery_id",
        "Personal Review delivery",
    )
    # Finalization is deliberately separate from the content-addressed delivery record:
    # its measured value is sampled after that record has been persisted.
    finalized_at, finalized_baseline = _clock_sample(clock, wall_clock)
    final_continuity = (
        continuity
        and abs(finalized_baseline - baseline) <= CLOCK_BASELINE_TOLERANCE_SECONDS
        and _clock_session_marker_from_baseline(finalized_baseline) == clock_state.get("session_marker")
    )
    final_elapsed = finalized_at - started if final_continuity else None
    finalization = {
        "schema_version": 1,
        "artifact_type": "personal_review_delivery_finalization",
        "status": "delivered" if final_continuity else "delivered_timing_unavailable",
        "completion_status": workflow["completion_state"],
        "delivery": {"path": persisted["path"], "sha256": persisted["sha256"]},
        "timing": {
            "elapsed_seconds": final_elapsed,
            "target_seconds": target,
            "target_met": None,
            "continuity_available": final_continuity,
            "clock_source": _clock_source(clock, wall_clock),
            "wcl_network_measurement": "not_measured",
            "measured_through": "rendered_html_index_and_delivery_artifact_persisted",
            "excluded_tail": ["finalization_record_write", "stdout_serialization"],
        },
        "stage_progress": {
            "retrieval": "completed",
            "agent_synthesis": "unavailable",
            "validation": "completed",
            "rendering": "completed",
        },
        "target_assessment": "unavailable_unmeasured_agent_synthesis",
    }
    finalization_path, finalization_ref, finalization_artifact = _persist_finalization(
        output_dir.expanduser().resolve() / "personal-deliveries", finalization
    )
    return {
        "artifact": finalization_artifact,
        "path": str(finalization_path),
        "sha256": finalization_ref["sha256"],
        "elapsed_seconds": final_elapsed,
        "target_met": finalization["timing"]["target_met"],
    }


def _workflow_invocation_timing(
    persisted: dict[str, Any],
    started: float,
    baseline: float,
    budget: float,
    clock: Callable[[], float],
    wall_clock: Callable[[], float],
) -> dict[str, Any]:
    completed, current_baseline = _clock_sample(clock, wall_clock)
    workflow = persisted["workflow"]
    continuity = (
        workflow["clock"]["continuity_available"] is True
        and "timing_continuity_unavailable" not in workflow["blockers"]
        and completed >= started
        and abs(current_baseline - baseline) <= CLOCK_BASELINE_TOLERANCE_SECONDS
    )
    return {
        "status": "measured" if continuity else "timing_unavailable",
        "elapsed_seconds": completed - started if continuity else None,
        "target_seconds": budget,
        "clock_source": _clock_source(clock, wall_clock),
        "wcl_network_measurement": "not_measured",
        "measured_through": "workflow_artifact_persisted",
        "excluded_tail": ["stdout_serialization"],
    }


def _timed(stages: dict[str, float], name: str, clock: Callable[[], float], operation: Callable[[], Any]) -> Any:
    before = clock()
    result = operation()
    duration = clock() - before
    if name not in STAGE_NAMES or not _nonnegative(duration):
        raise InputError("Personal Review monotonic stage timing is invalid.")
    stages[name] = stages.get(name, 0.0) + duration
    return result


def _optional_analysis(path: Path) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if not path.is_file():
        return None, None
    analysis, ref = _read_snapshot(path, "Personal Analysis")
    evidence = analysis.get("evidence")
    if not isinstance(evidence, dict):
        raise InputError("Personal Analysis evidence provenance is malformed.")
    manifest = evidence.get("manifest_path")
    index = evidence.get("index_path")
    if not isinstance(manifest, str) or not isinstance(index, str):
        raise InputError("Personal Analysis evidence provenance is incomplete.")
    if not Path(manifest).is_file() or not Path(index).is_file():
        return None, None
    return analysis, ref


def _optional_profile(path: Path, kind: str) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if not path.is_file():
        return None, None
    value, ref = _read_snapshot(path, f"{kind.title()} Profile")
    return validate_profile(value, kind), ref


def _load_previous(
    path: Path, cohort_ref: dict[str, str], output_dir: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    if not isinstance(path, Path):
        raise InputError("Personal Review workflow requires --previous-workflow from initialization.")
    path = path.expanduser().resolve()
    if path.parent != (output_dir / "personal-workflows").resolve() or path.name == "index.json":
        raise InputError("Previous Personal Review workflow must use the registered workflow artifact location.")
    previous, previous_ref = _read_snapshot(path, "previous Personal Review workflow")
    previous = verify_personal_workflow(previous)
    _verify_registered_workflow(path, previous, previous_ref)
    ref = (previous.get("artifacts") or {}).get("ranking_cohort")
    if ref is not None and ref != cohort_ref:
        raise InputError("Previous Personal Review workflow belongs to a different Ranking Cohort.")
    return previous, previous_ref


def _merge_reference_paths(previous: dict[str, Any] | None, paths: list[Path]) -> list[Path]:
    values = []
    if previous:
        for ref in (previous.get("artifacts") or {}).get("reference_analyses", []):
            ref = _object(ref, "Previous workflow Reference Sample")
            path = Path(str(ref.get("path")))
            if ref != _snapshot_ref(path):
                raise InputError("Previous workflow Reference Sample hash is invalid.")
            values.append(path.resolve())
    values.extend(path.expanduser().resolve() for path in paths)
    return list(dict.fromkeys(values))


def _merge_artifact_path(ref: dict[str, str], paths: list[Path], label: str) -> list[Path]:
    path = Path(str(_object(ref, f"Previous workflow {label}").get("path"))).expanduser().resolve()
    if _snapshot_ref(path) != ref:
        raise InputError(f"Previous workflow {label} hash is invalid.")
    return list(dict.fromkeys([path, *(item.expanduser().resolve() for item in paths)]))


def _merge_progress_refs(previous: dict[str, Any] | None, paths: list[Path]) -> list[dict[str, str]]:
    refs = list((previous.get("artifacts") or {}).get("progress", [])) if previous else []
    for ref in refs:
        path = Path(str(_object(ref, "Personal Review progress reference").get("path")))
        if ref != _snapshot_ref(path):
            raise InputError("Personal Review progress reference hash is invalid.")
    refs.extend(_snapshot_ref(path.expanduser().resolve()) for path in paths)
    return list({(ref["path"], ref["sha256"]): ref for ref in refs}.values())


def _previous_rejections(previous: dict[str, Any] | None) -> dict[str, str]:
    if not previous:
        return {}
    result = {}
    for item in previous.get("candidate_progress", []):
        if isinstance(item, dict) and item.get("status") == "rejected":
            result[str(item.get("candidate_id"))] = str(item.get("reason"))
    return result


def _candidate_progress(
    candidates: list[dict[str, Any]], analyses: list[dict[str, Any]], rejections: dict[str, str]
) -> list[dict[str, str]]:
    accepted = {_analysis_candidate_id(value) for value in analyses} - set(rejections)
    return [
        {"candidate_id": candidate_id, "status": "rejected", "reason": rejections[candidate_id]}
        if candidate_id in rejections else {"candidate_id": candidate_id, "status": "qualified"}
        for candidate in candidates
        if (candidate_id := _candidate_id(candidate)) in accepted or candidate_id in rejections
    ]


def _cohort_candidates(cohort: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = cohort.get("eligible_recent_candidates")
    if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
        raise InputError("Ranking Cohort has no eligible recent candidates.")
    ids = [_candidate_id(item) for item in candidates]
    if len(ids) != len(set(ids)):
        raise InputError("Ranking Cohort contains duplicate candidate identities.")
    return candidates


def _candidate_id(candidate: dict[str, Any]) -> str:
    code, fight_id, source_id = candidate.get("report_code"), candidate.get("fight_id"), candidate.get("source_id")
    if not isinstance(code, str) or not code.isalnum() or type(fight_id) is not int or type(source_id) is not int:
        raise InputError("Ranking Candidate identity is incomplete.")
    return f"{code}:{fight_id}:{source_id}"


def _analysis_candidate_id(analysis: dict[str, Any]) -> str:
    identity = _object(analysis.get("identity"), "Reference Sample identity")
    player = _object(analysis.get("player"), "Reference Sample player")
    return _candidate_id({
        "report_code": identity.get("report_code"),
        "fight_id": identity.get("fight_id"),
        "source_id": player.get("actor_id"),
    })


def _candidate_by_id(candidates: list[dict[str, Any]], candidate_id: str) -> dict[str, Any]:
    match = next((item for item in candidates if _candidate_id(item) == candidate_id), None)
    if match is None:
        raise InputError("Candidate progress is absent from the current Ranking Cohort.")
    return match


def _persist_result(output_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    directory = output_dir / "personal-workflows"
    persisted = _persist_content_artifact(directory, result, "workflow_id", "Personal Review workflow")
    index_path = directory / "index.json"
    with artifact_lock(index_path):
        index = {"schema_version": 1, "artifact_type": "personal_review_workflow_index", "artifacts": {}}
        if index_path.exists():
            index = _read_snapshot(index_path, "Personal Review workflow artifact index")[0]
        artifacts = index.setdefault("artifacts", {})
        if not isinstance(artifacts, dict):
            raise InputError("Personal Review workflow artifact index is malformed.")
        existing = artifacts.get(persisted["artifact"]["workflow_id"])
        if existing is not None and existing != {"path": persisted["path"], "sha256": persisted["sha256"]}:
            raise InputError("Personal Review workflow artifact index has an invalid identity.")
        artifacts[persisted["artifact"]["workflow_id"]] = {
            "path": persisted["path"], "sha256": persisted["sha256"]
        }
        atomic_write_json(index_path, index)
    verify_personal_workflow(persisted["artifact"])
    return {
        "workflow": persisted["artifact"],
        "workflow_path": persisted["path"],
        "workflow_sha256": persisted["sha256"],
    }


def _verify_profile_identity(encounter: dict[str, Any], specialization: dict[str, Any], expected: dict[str, Any]) -> None:
    for field in ("game_version", "partition_id", "encounter_id", "difficulty_id"):
        if encounter["identity"].get(field) != expected.get(field):
            raise InputError(f"Encounter Profile {field} does not match the Ranking Cohort.")
    for field in ("game_version", "partition_id", "class_name", "spec_name"):
        if specialization["identity"].get(field) != expected.get(field):
            raise InputError(f"Specialization Profile {field} does not match the Ranking Cohort.")


def _verify_selected_identity(value: Any) -> dict[str, Any]:
    identity = _object(value, "Personal Review selected identity")
    if (
        set(identity) != {"report_code", "fight_id", "actor_id"}
        or not isinstance(identity.get("report_code"), str)
        or not identity["report_code"].isalnum()
        or type(identity.get("fight_id")) is not int
        or identity["fight_id"] <= 0
        or type(identity.get("actor_id")) is not int
        or identity["actor_id"] <= 0
    ):
        raise InputError("Personal Review selected identity is invalid.")
    return identity


def _verify_selected_analysis_identity(analysis: dict[str, Any], selected: Any) -> None:
    selected = _verify_selected_identity(selected)
    identity = _object(analysis.get("identity"), "Personal Analysis identity")
    player = _object(analysis.get("player"), "Personal Analysis player")
    if (
        identity.get("report_code") != selected["report_code"]
        or identity.get("fight_id") != selected["fight_id"]
        or player.get("actor_id") != selected["actor_id"]
    ):
        raise InputError("Personal Analysis does not match the selected WCL Report, Boss Attempt, and player.")


def _read_snapshot(path: Path, label: str) -> tuple[dict[str, Any], dict[str, str]]:
    path = path.expanduser().resolve()
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"{label} must be valid UTF-8 JSON.") from exc
    return _object(value, label), {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}


def _read_locked_snapshot(path: Path, label: str) -> tuple[dict[str, Any], dict[str, str]]:
    path = path.expanduser().resolve()
    with artifact_lock(path):
        return _read_snapshot(path, label)


def _benchmark_reference_evidence(benchmark: dict[str, Any]) -> list[dict[str, Any]]:
    samples = benchmark.get("reference_samples")
    if not isinstance(samples, list):
        raise InputError("Encounter Benchmark Reference Sample structure is invalid.")
    result = []
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("player"), dict) or not isinstance(sample.get("evidence"), dict):
            raise InputError("Encounter Benchmark Reference Sample provenance is incomplete.")
        evidence = sample["evidence"]
        result.append({
            "actor_id": sample["player"].get("actor_id"),
            "manifest": {
                "path": str(Path(str(evidence.get("manifest_path"))).expanduser().resolve()),
                "sha256": evidence.get("manifest_sha256"),
            },
            "index": {
                "path": str(Path(str(evidence.get("index_path"))).expanduser().resolve()),
                "sha256": evidence.get("index_sha256"),
            },
        })
    return result


def _snapshot_ref(path: Path) -> dict[str, str]:
    return _binary_snapshot_ref(path, "Personal Review progress artifact")


def _verify_registered_workflow(
    path: Path,
    workflow: dict[str, Any],
    workflow_ref: dict[str, str] | None = None,
    *,
    registry_dir: Path | None = None,
) -> None:
    path = path.expanduser().resolve()
    expected_registry = registry_dir.expanduser().resolve() if registry_dir is not None else None
    if (
        (expected_registry is not None and path.parent != expected_registry)
        or (expected_registry is None and path.parent.name != "personal-workflows")
        or path.name != f'{workflow["workflow_id"]}.json'
        or path.name == "index.json"
    ):
        raise InputError("Personal Review workflow path does not match its content ID.")
    current_ref = workflow_ref or _snapshot_ref(path)
    index_path = path.parent / "index.json"
    try:
        index = _read_snapshot(index_path, "Personal Review workflow artifact index")[0]
    except InputError as exc:
        raise InputError("Personal Review workflow has no registered artifact identity.") from exc
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, dict):
        raise InputError("Personal Review workflow artifact index is malformed.")
    entry = artifacts.get(workflow["workflow_id"])
    if entry != current_ref:
        raise InputError("Personal Review workflow is not registered by its artifact index.")


def _binary_snapshot_ref(path: Path, label: str) -> dict[str, str]:
    path = path.expanduser().resolve()
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise InputError(f"{label} is missing or unreadable.") from exc
    return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}


def _verify_refs_current(refs: list[dict[str, str]]) -> None:
    for ref in refs:
        if _snapshot_ref(Path(ref["path"])) != ref:
            raise InputError("Personal Review input changed during workflow validation.")


def _verify_workflow_artifacts(artifacts: dict[str, Any]) -> None:
    requested = artifacts.get("requested_personal_analysis_path")
    if requested is not None and (not isinstance(requested, str) or not requested):
        raise InputError("Personal Review workflow requested Analysis path is invalid.")
    for field in (
        "personal_analysis", "ranking_cohort", "encounter_profile",
        "specialization_profile", "encounter_benchmark", "previous_workflow",
    ):
        ref = artifacts.get(field)
        if ref is not None:
            _verify_artifact_ref(ref, f"Personal Review workflow {field}")
    for field in ("reference_analyses", "progress"):
        refs = artifacts.get(field)
        if not isinstance(refs, list):
            raise InputError(f"Personal Review workflow {field} must be a JSON array.")
        for ref in refs:
            _verify_artifact_ref(ref, f"Personal Review workflow {field} reference")
    evidence = artifacts.get("benchmark_reference_evidence")
    if not isinstance(evidence, list):
        raise InputError("Personal Review workflow Benchmark evidence must be a JSON array.")
    for item in evidence:
        item = _object(item, "Personal Review workflow Benchmark evidence")
        if type(item.get("actor_id")) is not int or item["actor_id"] <= 0:
            raise InputError("Personal Review workflow Benchmark evidence actor is invalid.")
        _verify_artifact_ref(item.get("manifest"), "Personal Review workflow Benchmark manifest")
        _verify_artifact_ref(item.get("index"), "Personal Review workflow Benchmark index")


def _verify_artifact_ref(value: Any, label: str) -> None:
    ref = _object(value, label)
    if (
        set(ref) != {"path", "sha256"}
        or not isinstance(ref.get("path"), str)
        or not ref["path"]
        or not isinstance(ref.get("sha256"), str)
        or len(ref["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in ref["sha256"])
    ):
        raise InputError(f"{label} is invalid.")


def _persist_content_artifact(
    directory: Path,
    body: dict[str, Any],
    id_field: str,
    label: str,
) -> dict[str, Any]:
    artifact_id = _content_id(body)
    artifact = body | {id_field: artifact_id}
    path = directory / f"{artifact_id}.json"
    expected_bytes = _json_file_bytes(artifact)
    created = False
    with artifact_lock(path):
        if path.exists():
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise InputError(f"Existing {label} is unreadable.") from exc
            if payload != expected_bytes:
                raise InputError(f"Existing {label} has an invalid identity.")
        else:
            atomic_write_json(path, artifact)
            created = True
            payload = path.read_bytes()
            if payload != expected_bytes:
                raise InputError(f"Persisted {label} does not match its validated content.")
        ref = {"path": str(path.resolve()), "sha256": hashlib.sha256(payload).hexdigest()}
    return {"artifact": artifact, "path": str(path), "sha256": ref["sha256"], "created": created}


def _persist_finalization(directory: Path, body: dict[str, Any]) -> tuple[Path, dict[str, str], dict[str, Any]]:
    persisted = _persist_content_artifact(directory, body, "finalization_id", "Personal Review delivery finalization")
    return Path(persisted["path"]), {"path": persisted["path"], "sha256": persisted["sha256"]}, persisted["artifact"]


def _clock_sample(
    clock: Callable[[], float], wall_clock: Callable[[], float]
) -> tuple[float, float]:
    monotonic_value = clock()
    wall_value = wall_clock()
    baseline = wall_value - monotonic_value
    if not _nonnegative(monotonic_value) or not _finite(wall_value) or not _finite(baseline):
        raise InputError("Personal Review system clock values are invalid.")
    return monotonic_value, baseline


def _clock_source(clock: Callable[[], float], wall_clock: Callable[[], float]) -> str:
    if clock is time.monotonic and wall_clock is time.time:
        return "local_monotonic_and_wall_clock"
    return "deterministic_injected"


def _clock_session_marker(wall_value: float, monotonic_value: float) -> str:
    """Persist a compact boot/session fingerprint from the wall-minus-monotonic baseline."""
    return _clock_session_marker_from_baseline(wall_value - monotonic_value)


def _clock_session_marker_from_baseline(baseline: float) -> str:
    if not _finite(baseline):
        raise InputError("Personal Review system clock values are invalid.")
    return hashlib.sha256(str(int(round(baseline))).encode("ascii")).hexdigest()[:16]


def _content_id(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json_file_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be a JSON object.")
    return value


def _nonnegative(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < float("inf")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < float("inf")
