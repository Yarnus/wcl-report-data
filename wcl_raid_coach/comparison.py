from __future__ import annotations

from pathlib import Path
from typing import Any

from .analysis import analyze_player
from .cohort import verify_benchmark
from .errors import InputError


def compare_player(
    target: dict[str, Any], benchmark: dict[str, Any], *, signing_key: str | None = None
) -> dict[str, Any]:
    if not isinstance(target, dict) or not isinstance(benchmark, dict):
        raise InputError("Personal Review and Encounter Benchmark must be JSON objects.")
    if signing_key is not None:
        verify_benchmark(benchmark, signing_key)
        _verify_analysis_evidence(target, signing_key)
    target_identity = target.get("comparison_identity")
    benchmark_identity = benchmark.get("identity")
    if not isinstance(target_identity, dict) or not isinstance(benchmark_identity, dict):
        raise InputError("Personal Review comparison identities are missing.")
    if target_identity != benchmark_identity:
        raise InputError("Personal Review and Encounter Benchmark hard conditions do not match.")
    metrics = target.get("metrics")
    benchmark_metrics = benchmark.get("metrics")
    if not isinstance(metrics, dict) or not isinstance(benchmark_metrics, dict):
        raise InputError("Personal Review metrics are malformed.")
    target_casts = metrics.get("casts") if isinstance(metrics.get("casts"), dict) else {}
    median_casts = benchmark_metrics.get("casts_median")
    median_casts = median_casts if isinstance(median_casts, dict) else {}
    all_abilities = sorted(set(target_casts) | set(median_casts))
    cast_deltas = {
        ability: float(target_casts.get(ability, 0)) - float(median_casts.get(ability, 0))
        for ability in all_abilities
    }
    damage_median = benchmark_metrics.get("damage_total_median")
    damage_delta = None
    if isinstance(damage_median, (int, float)) and isinstance(metrics.get("damage_total"), (int, float)):
        damage_delta = metrics["damage_total"] - damage_median
    return {
        "schema_version": 1,
        "identity": dict(target_identity),
        "target": target.get("player"),
        "benchmark_sample_count": benchmark.get("sample_count"),
        "confidence": benchmark.get("confidence"),
        "guardrails": {"player_death": bool(metrics.get("deaths"))},
        "metrics": {"damage_total_delta": damage_delta, "cast_count_deltas": cast_deltas},
        "claim_limits": {
            "stable_patterns_allowed": benchmark.get("stable_pattern_claims_allowed") is True,
            "damage_delta_is_achievable_improvement": False,
        },
    }


def _verify_analysis_evidence(analysis: dict[str, Any], signing_key: str) -> None:
    evidence = analysis.get("evidence")
    player = analysis.get("player")
    identity = analysis.get("comparison_identity")
    if not isinstance(evidence, dict) or not isinstance(player, dict) or not isinstance(identity, dict):
        raise InputError("Personal Review evidence provenance is missing.")
    actor_id = player.get("actor_id")
    if not isinstance(actor_id, int) or isinstance(actor_id, bool):
        raise InputError("Personal Review actor identity is malformed.")
    try:
        manifest_path = Path(str(evidence["manifest_path"]))
        index_path = Path(str(evidence["index_path"]))
    except KeyError as exc:
        raise InputError("Personal Review evidence provenance is incomplete.") from exc
    try:
        recomputed = analyze_player(
            manifest_path,
            index_path,
            actor_id,
            partition_id=identity.get("partition_id"),
            signing_key=signing_key,
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise InputError("Personal Review evidence could not be verified.") from exc
    if recomputed != analysis:
        raise InputError("Personal Review does not match its Complete Bundle evidence.")
