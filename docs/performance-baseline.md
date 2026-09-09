# Workflow performance baseline (#30)

## Reproduction and boundaries

Run from the repository root with Python 3.11+ and no dependencies:

```bash
python -m tools.benchmark --repetitions 3
python -m tools.benchmark --scenario personal_existing --repetitions 5
python -m unittest tests.test_diagnostics tests.test_benchmark
```

The tool reports environment, source revision, worktree dirtiness, individual runs and medians of numeric measurements. Setup is outside the measured region. Each repetition uses a fresh temporary workspace; only `cached_prepare` primes its Complete Bundle and mappings before timing. CLI parsing and execution occur in the same Python process; process startup and Agent work are excluded. Each CLI command still creates its normal fresh WCL client. Filesystem/OS caches are not flushed. Wall time uses `time.monotonic`; CPU time uses `time.process_time`. No live credentials are used and no live scenarios were measured.

Only HTTP transport and credential resolution are replaced. OAuth/GraphQL decoding, quota reservations, mappings, collection, checksums, analysis, assembly, rendering and delivery validation run normally. Wago fixtures have 400,000 unique SpellName rows, 36 encounters across 9 maps and 108 NPCs. They are synthetic, not current naming evidence. Report/event fixtures are deliberately small; these results cannot predict production CPU or network speed. Tools and test fixtures are repository-only and excluded by `PACKAGE_PATHS`.

| Scenario | Inputs and cache state | Measured boundary |
| --- | --- | --- |
| First inspect | `AbC123`, empty roots; synthetic full mapping tables | CLI inspect including mapping initialization and Report Index |
| Cold prepare | `AbC123`, Boss Attempt 1, empty roots; one terminal event page | CLI prepare including mapping, metadata, collection and final Report Revision |
| Cached prepare | Same selection, Complete Bundle and mapping primed outside timing | CLI prepare, metadata refresh and deep Complete Bundle validation |
| Mechanic Review + follow-up | Supported encounter 3445, Boss Attempt 1, player 10, anchor 0 ms; one page each | Compact mechanics then explicit Focused Evidence Window in a second CLI invocation; no automatic candidate selection |
| Personal Review, existing Complete Bundles | Target Boss Attempt 7 plus Reference Samples 8/9/10; four Canonical Events each; Profiles and mappings present | Workflow initialization, three-sample Benchmark construction, comparison, assembly, rendering and finalization; all evidence revalidation enabled |
| Multi-Boss Raid Guide acquisition/reuse | Two encounters 5000/5001, separate Cohorts, three candidates each, shared Specialization Profile; initially empty roots | Two ranking pages, six prepares/analyses, two Benchmarks, Guide Snapshot/render; then deep Benchmark reuse validation and Snapshot/render reuse |

Ranking fixtures supply source IDs and a current timestamp, so CandidateSource resolution and expired-candidate behavior are not measured here. No retries or lock contention occur in these six runs; deterministic diagnostic tests exercise retry and lock-wait timing separately. The Guide reuse portion performs no additional HTTP requests. Profile source text is synthetic; no external guide retrieval or Agent synthesis is represented.

## Initial results

Measured on 2026-09-09, macOS 26.6.1 arm64, Python 3.12.13, base revision `59615405212210cc8bfbf7d43a4d5e3ee8bf3e35` plus the #30 instrumentation/worktree changes. Three repetitions, medians below. The benchmark source and regression checks define the comparable fixture. WCL attempts include OAuth and quota probes; Wago attempts are separate. Received bytes include both providers and vary slightly with ranking timestamps/compression.

| Scenario | WCL attempts | Wago attempts | Canonical Event passes | Wall ms | CPU ms | Received bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| First inspect | 3 | 7 | 0 | 627.353 | 620.123 | 7,783,907 |
| Cold prepare | 5 | 1 | 0 | 618.232 | 615.333 | 7,778,928 |
| Cached prepare | 3 | 0 | 1 | 177.779 | 177.041 | 816 |
| Mechanic Review + follow-up | 10 | 0 | 0 | 6.552 | 6.536 | 2,237 |
| Personal Review, existing Complete Bundles | 0 | 0 | 78 | 62.895 | 62.393 | 0 |
| Multi-Boss Raid Guide acquisition/reuse | 36 | 7 | 48 | 2,381.399 | 2,359.147 | 7,790,698 |

The tool's JSON includes per-operation network durations and per-stage inclusive/exclusive timings for each run. These are measured local fixture execution times, not WCL latency or speedup promises. In particular, 78 passes across independent Personal Review trust boundaries are not 78 redundant passes that can all be removed: later optimization must preserve assembly, renderer and delivery validation independently.

Unrun: live WCL scenarios, real Wago downloads, external guide retrieval, Windows measurements, Python 3.11 runtime, realistic large combat streams, OS-cold filesystem caches, multi-process contention, Agent synthesis and end-to-end human delivery. Shared quota changes never establish attributable request cost.

## Measurement ownership

`wcl_raid_coach/diagnostics.py` owns opt-in context-local aggregation. HTTP attempts are measured at WCL/Wago transport boundaries; domain modules mark mapping, validation, analysis, assembly/render and lock acquisition boundaries. `__main__.py` enables and emits diagnostics without changing command payloads or persisted identities. `tools/benchmark.py` owns fixture orchestration and repeatable medians, using existing repository test data. No measurement data is written into Personal Review timing artifacts. Runtime guidance is in the paired `references/performance.md` and `references/performance.en.md`.
## Shared scheduling stage (#31)

`wcl_raid_coach/api_schedule.py` now owns the per-OS-user gate, reusing `dataset._file_lock` for POSIX/Windows locking and `storage.atomic_write_json` for state. OS account-directory lookup is independent of environment-provided home paths. The gate is acquired after dataset/cache/artifact and local token locks; it never recursively authenticates or probes. State is validated on each acquisition; unknown or interrupted quota state requires a coordinated probe or a domain error. Every attempt retains conservative accounting until an API observation replaces it. No tokens or credential identities are stored.

With identical fixture inputs, cached prepare uses 2 WCL attempts, Mechanic Review plus follow-up uses 9, and the multi-Boss Guide uses 29; other #30 counts and Canonical Event passes are unchanged. These reductions come from reusing shared quota observations, not reduced event or metadata collection. Actual POSIX spawn tests verify exclusion, cross-process 429 propagation, the 10-second lock wait bound, and recovery after process termination. Windows execution remains unrun on this macOS host.
Three-repeat #31 medians on the same environment (wall/CPU milliseconds): first inspect 622.814/619.600; cold prepare 620.497/617.254; cached prepare 183.733/182.441; Mechanic Review plus follow-up 15.325/14.921; Personal Review 62.381/61.777; multi-Boss Guide 2439.617/2422.515. Shared-state locking and atomic writes add local overhead despite fewer quota probes. No measured wall-clock improvement is claimed for this stage.

## Deferred display mapping and metadata reuse (#32)

Pure inspect/prepare/query no longer initialize SpellName. Inspect validates only existing content mappings and otherwise returns WCL names. Thus cached prepare now primes only its Complete Bundle, with no display mapping prerequisite. Chinese output gates remain active.

Three repetitions on the same environment, using `python -m tools.benchmark --repetitions 3`:

| Scenario | WCL attempts | Wago attempts | Event passes | Wall ms | CPU ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| First inspect | 3 | 0 | 0 | 8.141 | 7.892 |
| Cold prepare | 5 | 0 | 0 | 13.239 | 12.709 |
| Cached prepare | 2 | 0 | 1 | 7.171 | 6.977 |
| Mechanic Review + follow-up | 9 | 0 | 0 | 15.726 | 15.209 |
| Personal Review | 0 | 0 | 78 | 63.025 | 62.515 |
| Multi-Boss Guide | 29 | 7 | 48 | 1379.026 | 1370.458 |

Regression tests separately exercise two explicitly selected Boss Attempts sharing one Report Index request and four candidate identity checks sharing one CandidateSource request (previously four). The WclClient created for candidate discovery owns this in-memory `(report_code, fight_id)` cache; each identity still undergoes character/server/class/spec matching. It is not persisted or used to qualify Reference Samples. Guide fixtures already supply source IDs, so their request count does not measure this reduction. These synthetic local results exclude live network latency and Agent synthesis. `make check` passed 335 tests, compileall, link checks, and diff whitespace checks.

## Single event traversal (#33)

`dataset._complete_bundle_inputs` validates manifest, available Raw Pages, Report Index, identity, and compressed-file hash. `dataset._validated_events` owns the shared decompression/parser and final canonical hash/count checks. Standalone validation, query, and player analysis exhaust it before returning. Query retains only its bounded result; analysis retains aggregate metrics. Each independent assembly/render/delivery caller still performs fresh validation. No trusted-validation cache is introduced.

Diagnostics now expose `bundle_input_validation` separately. Fused event validation/calculation is included in the enclosing query/player-analysis duration; the standalone validator retains `complete_bundle_validation`. Event passes fall from 78 to 39 for Personal Review and 48 to 24 for Guide; cached prepare stays at one. Three-repeat wall/CPU ms on the same host: inspect 8.696/8.356; cold prepare 13.329/12.915; cached prepare 6.993/6.831; mechanics follow-up 16.713/16.174; Personal Review 67.508/66.210; Guide 1409.141/1399.763. Requests are unchanged from #32. These small fixtures do not demonstrate a wall-clock improvement for #33; the deterministic improvement is halving analysis decompression passes.

The 30,005-event regression verifies one gzip open per query/analysis and a peak traced allocation below 4 MiB with a one-result query and fixed aggregation keys. Trailing invalid JSON, incorrect sequence, missing rows and truncated gzip fail after partial accumulation, including when the query limit was already reached. Existing metrics/cursor, corruption, workflow and report checks pass: `make check`, 337 tests and compileall/diff checks.

## Single-process triage (#34)

`MechanicReviewService.triage` owns phase orchestration and compact candidate selection. Its report tuple lives only within the invocation and is passed to existing review/window validation; each window performs an additional pre-phase revision probe instead of fetching full metadata again. No event persistence or alternate collection path is introduced. `tools.benchmark` adds `triage` alongside the retained multi-command baseline using the same supported encounter/player event fixture.

Three-repeat triage medians: 8 WCL attempts, 0 Wago attempts, 0 Canonical Event passes, wall 10.703 ms, CPU 10.325 ms. Counts are OAuth 1, quota 1, ReportIndex 1, MechanicEvents 1, FocusedEvents 1, ReportRevision 3. The #30 multi-command baseline used 10 attempts; #31-33 used 9. Compare local synthetic timings only, not real WCL performance. Candidate order/facts match the separate procedure; ties, grouping, time limits, team exclusion, no candidates, death supplementation, and phase/API failures are tested. `make check` passed 343 tests plus compileall and diff checks.

## Final series validation (#35)

The Skill entrypoint owns routing, first actions and mandatory gates. Three paired workflow references own mechanics/triage, Personal Review, and Guide acquisition/delivery details. Artifact schemas remain authoritative in the paired data contract. `references/` already belongs to the release allowlist; no packaging rule changed. The original entrypoint was 331 lines/32,404 UTF-8 bytes; the new entrypoint is 71 lines/6,057 bytes. This reduction is not an Agent latency measurement.

Final three-repeat medians on macOS 26.6.1 arm64/Python 3.12.13, same synthetic inputs and base revision plus this series' worktree. The five baseline workflow families remain represented; cold/cached prepare are separate scenarios, and triage is compared to the retained multi-command procedure.

| Scenario/cache state | WCL attempts before → after | Wago before → after | Event passes before → after | Wall ms before → after | CPU ms before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| First inspect, empty roots | 3 → 3 | 7 → 0 | 0 → 0 | 627.353 → 7.587 | 620.123 → 7.337 |
| Cold prepare, empty roots | 5 → 5 | 1 → 0 | 0 → 0 | 618.232 → 12.459 | 615.333 → 12.024 |
| Cached prepare, primed Complete Bundle | 3 → 2 | 0 → 0 | 1 → 1 | 177.779 → 7.891 | 177.041 → 7.597 |
| Mechanics plus separate follow-up, no persistence | 10 → 9 | 0 → 0 | 0 → 0 | 6.552 → 15.967 | 6.536 → 15.422 |
| Same supported priority case using triage | 10 → 8 | 0 → 0 | 0 → 0 | 6.552 → 10.835 | 6.536 → 10.488 |
| Personal Review, four existing Complete Bundles | 0 → 0 | 0 → 0 | 78 → 39 | 62.895 → 58.765 | 62.393 → 57.985 |
| Two-Boss Guide acquisition and deep reuse | 36 → 29 | 7 → 7 | 48 → 24 | 2381.399 → 1363.892 | 2359.147 → 1353.293 |

Shared coordination adds local lock/state-write overhead to the tiny mechanics fixture despite fewer requests. Cold-start gains here largely remove synthetic 400,000-row SpellName work; real network savings are not measured. Final event validation additionally checks consumer field shapes before yielding, preserving domain errors on malformed input. Inspect tries its optional mapping lock without waiting and returns WCL names when busy. Shared anomaly windows supplement each affected player's missing pre-death interval separately.

### Representative prompt walkthroughs

These are manual route/sequence checks against the final documents, backed by deterministic CLI parser and runtime tests; no separate LLM prompt experiment or Agent synthesis timing was run.

| Prompt | On-demand material | Expected sequence and verified boundary |
| --- | --- | --- |
| How to use? | Entrypoint help only | Menu, no CLI/WCL; usage-help test |
| List this bare report | Entrypoint data route | doctor → inspect → explicit selection; no mapping download |
| Prepare attempts 1 and 3 | Entrypoint data route | doctor → one batch prepare; one ReportIndex request, no independent inspect |
| Who needs priority review? numeric fight | Mechanics reference | doctor → triage; one client/metadata, complete windows and phase revision checks |
| Priority review with no verified target anomaly | Mechanics reference | triage → no_supported_candidate; no focused requests, no correctness verdict |
| Cold Personal Review | Personal reference; Guide reference only for missing acquisition | selection → workflow-init → target/Profiles/Cohort acquisition → workflow, three qualified samples; budget checked before optional work |
| Reused Personal Review | Personal reference | workflow-init → local original Cohort/Profile/Benchmark lookup → deep workflow verification → compare/personal-report; retain eligible 3–10 samples |
| Partial Personal Review | Personal reference and contract when constructing advice | complete player evidence plus workflow-derived 0–2 samples → partial personal-report, no Benchmark/Comparison |
| H7/H8 specialization guide | Guide reference | resolve → confirm → compatible shared Specialization Profile, independent Encounter/Cohort/Benchmark evidence → missing chapters only → guide/guide-report |

Issue #29 was OPEN when checked: external guide retrieval fallback remains separate, with no implementation or prerequisite introduced here. Source currentness and actual-content verification remain required.

Package smoke ran through Makefile using a temporary Git index tree (`dd18ef287be33dc979870a8b77fb55dce460b45e`) containing working-tree release inputs, without committing or changing the user's index. ZIP integrity, extracted CLI help, all six workflow references/runtime modules, 83 local archive links, and exclusion of tools/tests/docs/__pycache__ passed (45 files). Markdown CLI examples in the entrypoint and six workflows parse with the current parser; placeholders are substituted with valid scalar types for this check. Runtime links are checked recursively across references.

Remaining unrun checks: live WCL/Wago, external guide retrieval, Windows execution, Python 3.11 runtime, realistic production combat streams, OS-cold filesystem caches, Agent synthesis and human delivery. POSIX multi-process coordination and a 30,005-event bounded-memory fixture are tested. Counts are deterministic fixture observations; timings are local synthetic measurements, not network performance or delivery guarantees.

The final pre-release `make check` passed 347 tests, compileall and `git diff --check`. Standards/spec review found and verified fixes for malformed-event domain errors, optional mapping-lock waiting and per-player death supplementation. Pre-release review also restored the complete bilingual Advice draft example and allowed enums, with full/partial validation of both documented examples.
