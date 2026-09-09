# Personal Review

[中文](workflow-personal.md). Preserve the [Skill entrypoint](../SKILL.md) gates. When constructing Profiles or Advice, read the coaching artifact, Report Document and timing sections of the [data contract](data-contract.en.md). Use artifact paths rather than copying their fields through messages.

## Start timing immediately after selection

Inspect bare reports and obtain explicit attempt/player selection; numeric fight/source in a URL must identify the intended objects. Immediately initialize, before doctor, target Bundle retrieval, candidate discovery or Profile retrieval/synthesis:

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-workflow-init "https://www.warcraftlogs.com/reports/<REPORT_CODE>#fight=<FIGHT_ID>&source=<ACTOR_ID>"
```

Keep workflow_path. Initial blocked, retrieval in_progress, agent_synthesis unavailable and personal_analysis null are expected. Prepare the target directly, then calculate facts:

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach review "<MANIFEST_PATH>" --index "<REPORT_INDEX_PATH>" --source-id <ACTOR_ID> --partition-id <PARTITION_ID> --output "<WORK_DIR>/analysis.json"
```

## Search local reuse before rankings

Search compatible local Encounter Benchmarks together with their bound original Ranking Cohorts, both Profiles, Reference Analyses and Complete Bundles before refreshing rankings. Game version, encounter, difficulty, class, spec, partition and Profile IDs/sources must agree and remain current. Encounter/spec alone is insufficient. Let personal-workflow deeply validate and reconstruct the exact Benchmark; paths, modification times, sizes and earlier success do not establish trust.

Use all existing eligible three-to-ten samples immediately; do not wait for ten. Three-to-nine is low confidence, ten normal. Without reuse, target three qualified Reference Samples. Candidates are not samples. If acquisition is needed, read [guide acquisition](workflow-guide.en.md), retaining the Personal Review target of three; the underlying candidates default maximum remains ten. Verify actual source text and current versions; failed fetches, snippets and generic class overviews do not establish that a specialization guide was read.

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-workflow "<PERSONAL_ANALYSIS_PATH>" --cohort "<ORIGINAL_COHORT_PATH>" --encounter-profile "<ENCOUNTER_PROFILE>" --specialization-profile "<SPECIALIZATION_PROFILE>" --reference-analysis "<REFERENCE_ANALYSIS>" --benchmark "<EXISTING_BENCHMARK>" --previous-workflow "<INITIAL_OR_LATEST_WORKFLOW>" --progress "<CHECKPOINT_PATH>"
```

Omit absent optional benchmark/reference/progress arguments. Always pass the initial/latest canonical workflow with valid registry, path and hashes. Record failures by stable identity, for example rejection ABC123:7:42=player_death. Keep the complete queried deduplicated ranking page and resume by candidate identity, never counts.

For acquiring, process only next_ranking_candidate, with the workflow's 20-second reserve checked before every optional action. Comparison_ready runs compare/full delivery; partial_ready creates no Benchmark/Comparison. Only terminal pagination proof establishes ranking_page_exhausted; otherwise use ranking_cohort_refresh_required. API failures stop optional work and preserve blockers/progress; in-flight requests can exceed budget. Progress binds checkpoint hashes without claiming completeness. Missing player evidence is blocked and cannot produce a report.

All calls inherit the initial monotonic/wall-clock origin; gaps cover network, Profiles and Agent synthesis. No caller timing fields. Clock rollback or baseline discontinuity retains progress, records timing_continuity_unavailable and stops optional work; session markers are diagnostic only. Final Agent synthesis is unavailable, target_met null and wcl_network_measurement not_measured. The 180/30-second targets are not guarantees.

## Deterministic delivery

After workflow builds/validates the Benchmark, save the exact Comparison:

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach compare "<PERSONAL_ANALYSIS_PATH>" "<ENCOUNTER_BENCHMARK_PATH>" --output "<COMPARISON_PATH>"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-report "<PERSONAL_ANALYSIS_PATH>" "<ENCOUNTER_BENCHMARK_PATH>" "<COMPARISON_PATH>" --workflow "<COMPARISON_READY_WORKFLOW>" --advice "<WORK_DIR>/advice-draft.json" --encounter-profile "<ENCOUNTER_PROFILE>" --specialization-profile "<SPECIALIZATION_PROFILE>" --locale en
```

For a finished workflow with zero-to-two qualified samples:

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach personal-report "<PERSONAL_ANALYSIS_PATH>" --workflow "<PARTIAL_READY_WORKFLOW>" --encounter-profile "<ENCOUNTER_PROFILE>" --specialization-profile "<SPECIALIZATION_PROFILE>" --advice "<WORK_DIR>/advice-draft.json" --locale en
```

Partial still revalidates player evidence, Cohort, eligibility, Reference Bundles and Profiles, deriving sample count from evidence. Comparison is unavailable; no caller count or Benchmark/Comparison is accepted. Incomplete player evidence cannot use partial. Omit advice when unavailable; Chinese uses zh-CN. Deliver summary/report.html_path and retain advice/document/hash/index audit identities.

Assembly, renderer and delivery independently revalidate sources and reconstruct exact Benchmark/Comparison. Deliver only after HTML/index and successful finalization. Reuse requires identical canonical bytes/hashes; damaged content is not overwritten. Immutable Advice/workflow/delivery orphans require explicit human or dedicated reference-aware cleanup. Report Document accepts schema 2; old schema 1 HTML remains viewable but cannot be rerendered.

## Advice and metrics

Complete Advice draft example (replace example IDs, values and source indices with current verified evidence; this is conditional experience-based advice, and the damage-total citation does not establish that ability usage should increase):

```json
{
  "schema_version": 2,
  "locale": "en",
  "items": [{
    "dimension": "output",
    "evidence_class": "experience_based",
    "action": {"kind": "use_ability", "ability_id": 2},
    "conditions": ["effective_window", "mechanic_safe"],
    "verification_goal": "check_ability_usage",
    "ability_ids": [2],
    "fact_references": [{"source": "personal_analysis", "path": "/metrics/damage_total", "value": 150}],
    "guidance_references": [{"profile_kind": "specialization", "source_index": 0}]
  }]
}
```

Allowed action.kind values: `use_ability`, `review_fact`, `observe_pattern`, `adjust_timing`. Conditions: `effective_window`, `mechanic_safe`, `target_available`, `next_attempt`. Verification goals: `compare_next_attempt`, `check_event_fact`, `check_ability_usage`. Fact references and evidence gates still follow the data contract and the requirements below.

The Agent synthesizes Advice schema 2 from verified artifacts/current Profile sources, without adding a model service. Use the finite action/condition/verification enums above, four dimensions output/survival/mechanics/team_contribution and event_supported/experience_based. Cite exact fact values and Profile kind/zero-based source index. Full-path Profile paths/hashes/IDs/sources must match the Benchmark; partial experience cites Profiles and event facts cite Personal Analysis. Reference validation does not certify prose.

All ability actions and ability_ids bind same-ID player_cast declarations; event support uses same-ID direct-player/key_action fields. Owned damage/healing, automatic/internal/pet and synthetic Melee 1 are audit-only. Survival cites deaths; team contribution cites interrupts/total healing/resources. Current Personal Review has no Mechanic Review source, so mechanics advice is conditional sourced experience only. Display key_action_* only, retaining zero medians; no casts_median fallback. Chinese advice requires a verified zhCN hit; ordinary facts may retain WCL names.

Retain exact revision/fight/actor, comparison hard conditions, Benchmark identity/confidence/sample count, totals, both durations, per-minute values and valid denominators; invalid denominators produce null. Normalization does not correct survival, downtime, phases, talents, gear or assignments, and medians are not prescriptions. Nonempty target lists require npc_game_id; migrate report-local IDs and rebuild downstream artifacts. Rebuild offline with complete local artifacts/mappings, otherwise acquire missing inputs. Mark missing advice unassessed in all four dimensions; no responsibility, causality or guaranteed improvement.
