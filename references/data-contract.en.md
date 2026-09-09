# Dataset Contract

This document is the English companion to [the Chinese data contract](data-contract.md). It defines the stable identity and completeness rules for prepared data.

## Identity

A prepared dataset is identified by:

```text
(report_code, report_revision, schema_version)
```

A Fight Bundle adds one numeric `fight_id`. Files from different Report Revisions must never be combined. `latest.json` is only a pointer; reproducible consumers use the revision recorded in each manifest.

## Report Index

`report.json` contains:

- report metadata and archive accessibility
- report actors and abilities
- every WCL fight classified as `boss` or `trash`
- team participants with actor ID, name, server, class, specialization, and item level
- each WCL zone ranking partition's positive integer `id`, non-empty `name`, nullable `compactName`, and boolean `default`
- `packable` and `unpackable_reason`

A WCL Report with raid Boss Attempts may also contain Mythic+ fights. Those Mythic+ fights remain in the Report Index with `unpackable_reason: "mythic_plus"`, but are omitted from `inspect` `fight_choices` and cannot produce a Fight Bundle. Pure Mythic+ reports are still rejected.

Fight selection and source hints from a particular input are returned by `inspect` rather than persisted in the immutable index. A source hint never filters actors or events.

`inspect` also returns one-based `encounter_choices` in the original WCL `zone.encounters` array order. This list is current-query selection metadata used to interpret Encounter Designators and is not persisted in existing Report Indices. Consumers must not sort it or filter out encounters absent from the report's fights.

Fight `difficulty` is the raw numeric ID returned by WCL. Resolve it against `report.zone.difficulties` from the same report. Do not use a static global mapping.

The compact `selected_fight` and `fight_choices` returned by `inspect` include the resolved `difficulty_name`. An unmatched ID produces `null`, not a guessed name.

## Fight Bundle

`manifest.json` is written last. Its presence with `complete: true` means that:

The manifest must contain `product: "wcl-raid-coach"`; Bundles produced by another product are not valid inputs to this product.

1. Every WCL event page reached `nextPageTimestamp: null`.
2. Pagination did not repeat a cursor.
3. Event timestamps remained ordered.
4. The Report Revision was unchanged after collection.
5. `events.jsonl.gz` was closed and hashed.

All pages use the same inclusive fight start and end timestamps. Bundles created by an older collection protocol are rejected and must be prepared again.

The manifest records event counts by type, Raw Page hashes, the compressed event-file hash, the uncompressed Canonical Event JSONL content hash, collection options, and unknown field counts. Hashes provide local content identity and corruption detection; they do not authenticate artifact origin.

## Canonical Events

Each gzip JSONL row has this envelope:

```json
{
  "sequence": 42,
  "report_time_ms": 123456,
  "fight_time_ms": 3456,
  "type": "damage",
  "source": {"actor_id": 100, "instance_id": 1},
  "target": {"actor_id": 17, "instance_id": null},
  "ability_id": 456789,
  "fields": {"amount": 1000, "absorbed": 200},
  "raw_ref": {"page": 1, "index": 42}
}
```

Actor and ability names live in `report.json`; IDs are event identity. Localized names are display data and must not be used as keys.

`ability-names.zhCN.json` in the data directory is current-client display enrichment kept outside the Report Index. When `inspect`, `prepare`, or `query` first needs it and the file is absent, the CLI downloads the complete zhCN `SpellName` table from Wago Tools; metadata records the client build, source, and hash. It may be applied only when a Canonical Event `ability_id` also matches Report Index `abilities[].gameID`. A hit still retains the WCL name, ability ID, and mapping build provenance; a miss uses the WCL name. Mapping updates do not alter Report Revision facts or Complete Bundle identity.

`content-names.zhCN.json` is separate current-content display enrichment limited to the current raid on Normal, Heroic, and Mythic and the configured eight Mythic+ maps. Maps and encounters use Wago IDs; each NPC record contains its `JournalEncounterCreature` ID, encounter, English name, and Chinese name. Wago data does not provide a reliable direct link to WCL NPC `gameID`, so the English-name index may be used only for display within encounter context and must not replace actor ID. Metadata records the shared client build, sources, and mapping hash for all Wago tables. Mapping updates do not modify a Report Index or Complete Bundle.

Known fields cover amounts, mitigation, healing, resources, health, aura stacks, casts, encounter metadata, combatant gear and talents, and observed combat statistics.

WCL event JSON is not frozen. New keys are counted under `unknown_fields`; their values remain only in the Raw Page cache until the schema explicitly adopts them.

Guide Snapshot Markdown must display Chinese SpellName and encounter names from verified Wago zhCN mappings; the JSON index may retain IDs, original WCL names, and mapping builds for audit.

## Query Contract

`query` streams the gzip file and returns at most `limit` rows. `matched` counts all matching rows after the input cursor. When `truncated` is true, `next_cursor` is the final returned sequence and can be passed to the next call.

Time filters use `fight_time_ms`, and their bounds are inclusive.

## Mechanic Evidence Set

A Mechanic Evidence Set is the ephemeral input to Mechanic Review for one numeric fight ID. It binds one WCL Report, Report Revision, fixed Boss Attempt time range, and Mechanic Ruleset. It contains raw WCL event objects returned by a server-side filter for ruleset ability IDs plus `death`, `interrupt`, and `dispel`; it is not a Canonical Event collection.

Collection preserves event order, rejects invalid or repeated pagination cursors, starts the first page at the Boss Attempt start, starts later pages at the current cursor, keeps the Boss Attempt end fixed, reaches an explicit `nextPageTimestamp: null`, and finally verifies that the Report Revision did not change. A fight's raw difficulty ID is still resolved through that report's `zone.difficulties` before selecting Normal, Heroic, or Mythic rules.

The Mechanic Evidence Set exists only in the current process and creates no Report Index, Raw Page, Fight Bundle, manifest, hash, or checkpoint. An interruption, rate limit, or failure requires collection to restart. Results record the ruleset version, sources, and `selection_policy: latest`. Here `latest` means the newest rules shipped in the installed package; rules are neither selected by report date nor refreshed online at runtime.

Per-mechanic counts describe only rule-defined event signals. A success or failure value is `null` when the log cannot establish it objectively. Only a pattern marked `verified` for the current difficulty may emit anomalies; `event_pattern_unverified` and observation rules emit none. An anomaly does not assign responsibility, performance, or wipe causality.

`coach mechanics ... --compact` derives only the current stdout view; it neither changes nor persists the Mechanic Evidence Set. A field allowlist excludes arbitrary raw WCL payloads. The view expands only anomalies involving players, retains only players in team-anomaly participant lists, caps expanded player anomalies at 20 per mechanic, and counts suppressed pet/NPC records and events. `player_anomaly_summary` provides complete per-player record counts, event counts, and first/last times independent of the display cap. Every mechanic exposes its `scope`: only `target` scope may rank individual follow-up candidates, while `team` scope remains a tied team fact. Mixed team anomalies separately declare player event counts and suppressed non-player event counts. Original mechanic counts remain unchanged, so suppression does not mean those events did not occur.

## Focused Evidence Window

`coach evidence <URL_WITH_NUMERIC_FIGHT> --at-ms <TIME> --player-id <ID> --expected-identity <TOKEN> [--window-ms <RADIUS>]` creates a process-local Focused Evidence Window for a fast follow-up question. The token comes from compact Mechanic Review's `evidence_identity` and binds the WCL Report, Report Revision, and Boss Attempt. The anchor and radius are fight-relative milliseconds; the radius defaults to 10,000 and is capped at 30,000, with the range clipped to the Boss Attempt bounds. Expected identity must match before collection, and Report Revision must match again after all pages. At most three distinct player IDs sharing that anchor are accepted, and each must resolve to a Player participant in that Boss Attempt.

Each participant is fully paginated over the same short range. All pages must remain ordered and inside the current query range, reject repeated cursors, and reach an explicit `nextPageTimestamp: null`. Each query retains only allowed events whose target report actor ID equals that participant, preventing cross-query duplicates. The complete matched set is time ordered; stdout returns at most 200 events, selecting deaths and resurrections first and then events nearest the anchor, and declares `matched_event_count`, `returned_event_count`, `truncated`, and the selection policy. Events contain only valid flat fields among `fight_time_ms`, event type, source/target/ability/extra ability IDs, amount, absorbed, overheal, overkill, current/maximum hit points, killer/killing ability IDs, and stack. `actors` and `abilities` explain only IDs referenced by returned events.

A Focused Evidence Window requests no resources and creates no Report Index, Raw Page, Fight Bundle, Complete Bundle, Canonical Event, manifest, hash, or checkpoint. It cannot be persisted or consumed by a Personal Benchmark or Guide. It supports only damage, healing, aura, death, and resurrection facts inside its window; top-level `judgment` and `causal_attribution` remain `null`, so it cannot establish player, healer, positioning, or wipe responsibility.

`coach mechanics <URL_WITH_NUMERIC_FIGHT> --report [--locale zh-CN|en]` is the CLI Mechanic Review persistence and rendering path. In the same process that completes collection and the revision recheck, it derives a schema `1` sanitized `mechanic_review` source from the actual result. The source may retain only WCL Report, Report Revision, Boss Attempt, and Mechanic Ruleset identity and metadata, page/event counts, supported conclusions or anomalies, phases, participants, and the flat minimal evidence excerpts allowed below. It cannot retain the complete filtered event range, a Raw Page, a Fight Bundle or Complete Bundle substitute, `raw_event`, `raw_events`, aura application objects, arbitrary WCL payloads, responsibility, or wipe causality.

The SHA-256 of the validated formatted JSON file bytes addresses the source at `outputs/mechanic-reviews/<sha256>.json`; an artifact lock and atomic write coordinate publication. Existing identical content is reused, while an identity mismatch is never overwritten. Persistence is not invoked when pagination does not reach explicit null, the Report Revision changes, or collection fails. Sanitization, source validation, or initial HTML rendering failure removes a newly created source so no misleading partial source remains.

## Report Document

A Report Document is presentation input, not evidence-layer data. Schema `2` is the only accepted Report Document schema. Existing schema `1` static HTML remains viewable, but schema `1` documents cannot be rerendered; rerun `personal-report` from current Analysis, Benchmark, and Comparison source artifacts to produce schema `2`. Unknown schemas are rejected.

The complete input shape follows. `phases`, each mechanic's `events`, and `actions` may be empty arrays:

```json
{
  "schema_version": 2,
  "document_type": "mechanic_review",
  "locale": "en",
  "title": "Encounter mechanic review",
  "subtitle": "Heroic Boss Attempt 17",
  "source_artifacts": [
    {"kind": "mechanic_review", "path": "/work/mechanic-review.json", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
  ],
  "identity": {
    "report_code": "AbC123",
    "report_revision": 7,
    "fight_id": 17,
    "encounter_name": "Encounter Name",
    "difficulty_name": "Heroic",
    "duration_ms": 342318,
    "outcome": "wipe",
    "boss_percentage": 32.7
  },
  "ruleset": {
    "version": "2026.09.1",
    "selection_policy": "latest",
    "sources": ["https://example.com/mechanic-source"]
  },
  "evidence": {"event_count": 184, "storage": "minimal_excerpts"},
  "phases": [{"name": "Phase one", "start_ms": 0, "end_ms": 342318}],
  "mechanics": [
    {
      "name": "Mechanic name",
      "status": "anomaly",
      "trigger_count": 18,
      "success_count": 14,
      "failure_count": 2,
      "description": "A reviewable conclusion and its limits.",
      "events": [
        {
          "fight_time_ms": 138440,
          "tone": "danger",
          "title": "Event title",
          "description": "The minimal event description supporting the conclusion.",
          "participants": ["Player 03"],
          "evidence_excerpt": {"event_type": "damage", "ability_id": 1284941}
        }
      ]
    }
  ],
  "actions": [{"title": "Next-attempt check", "description": "Change only one verifiable condition."}],
  "scope_note": "Anomalies do not assign player responsibility, performance, or wipe causality."
}
```

A `personal_review` has exactly the shared fields plus `identity`, `player`, `comparison`, `metrics`, `abilities`, and `advice`. A full comparison includes schema `4` `personal_analysis`, schema `3` `encounter_benchmark`, schema `3` `comparison`, a canonical schema `2` `personal_review_workflow`, and automatically attached ability-name artifacts. Comparison must exactly equal the recomputed result, and the workflow must bind the exact Cohort, both Profiles, Benchmark, and every Reference Sample's Complete Bundle provenance. A partial result with fewer than 3 qualified Reference Samples instead includes `personal_analysis`, both validated Profiles, schema `2` `personal_review_workflow`, and ability-name artifacts. Its qualified count must be derived by revalidating the workflow-bound Cohort and Reference Sample evidence, never supplied by a caller. It includes no Benchmark or Comparison artifact. Non-empty advice additionally requires schema `2` `coaching_advice`.

- `player`: positive integer `actor_id`, `name`, `class_name`, `spec_name`, nullable `item_level`, and boolean `anonymous`.
- `comparison`: the complete comparison hard conditions `game_version`, `partition_id`, `encounter_id`, `difficulty_id`, `class_name`, and `spec_name`, the exact `benchmark_id`, `sample_count` of at least 3, `confidence` of `low` or `normal`, and the fixed unmatched context disclosure: survival, downtime, phases, talents, gear, and assignments. IDs are positive, and class/spec must match `player`.
- Every partial reference metric is null with zero coverage, and `abilities` is empty. Personal Analysis is still recomputed from its Complete Bundle, and both Profiles are checked directly against its comparison identity. Experience-based Advice may cite only validated Profile sources; event-supported Advice may cite only Personal Analysis. Incomplete player evidence makes partial rendering fail.
- `metrics`: damage and healing totals remain present. Player duration, Reference Sample median/range duration, player/reference per-minute damage and healing, deltas, and independent valid Reference Sample counts are also included. Each reference rate is computed from one Reference Sample with a valid positive duration before aggregation. No valid denominator produces a null value and zero coverage. Normalization does not correct the unmatched context above.
- `abilities`: at most 100 direct-player key actions declared by the Specialization Profile with `action_type: "player_cast"`. Each retains identity/names, player and median counts, first-cast values, player/reference per-minute counts, delta, and valid Reference Sample count. The explicit declaration establishes action semantics, so a zero median remains present when every sample has zero casts. Raw, owned-actor, automatic, internal, and synthetic cast medians are never display fallbacks. WCL ability `1` has synthetic Melee semantics and cannot be treated as client Spell `1` or a suggested player action.
- `advice`: may be empty. Each item has an output, survival, mechanics, or team-contribution dimension; an event-supported or experience-based evidence class; an action; applicability conditions; a next-Boss-Attempt verification goal; ID-resolved Spells; local fact references; and current Profile guidance references. Event-supported items use an explicit dimension allowlist: output accepts only damage, healing, rate, and ability-ID player-action fields; survival accepts only death fields; team contribution accepts only interrupt, healing, resource-event, and ability-ID healing fields. An event-supported action with an ability ID must cite an eligible field for that same ability ID. Personal Review currently has no Mechanic Review source, so mechanics cannot be event-supported. Experience-based items require validated current Profile guidance and remain explicitly conditional. HTML keeps each item's action, Spells, conditions, verification goal, and references together. A dimension without advice is Not Evaluated, not passed.

A `raid_guide` has exactly the shared fields plus `identity`, `specialization`, `snapshot_id`, `ability_names_build`, and `chapters`; its sole source kind is `guide_snapshot`. Its `identity` contains `game_version`, positive `partition_id`, `difficulty_name`, `class_name`, and `spec_name`. The `snapshot_id` and both Profile IDs in each chapter must be SHA-256 digests.

- `chapters`: 1 to 20 chapters with unique encounter IDs. Each contains `encounter_id`, `encounter_name`, the exact `benchmark_id`, `sample_count` of at least 3, `confidence`, nullable `damage_total_median`, `abilities`, `target_damage`, `mechanic_anchors`, both Profile IDs, and `sources`.
- Chapter `abilities` retain only ability name, median casts, and median first-cast time; `target_damage` retains only numeric target ID and median damage; `mechanic_anchors` retain only name and nullable observed time.
- Chapter `sources` accept only an `encounter` or `specialization` kind, title, public HTTP(S) URL, and quote summary. Ruleset and chapter source URL authorities cannot contain user information. Query-string and fragment parameter names cannot be credential, key, token, authentication, or signature names after case, common separators, and percent encoding are normalized.

Personal Review advice cannot claim an unverified cause, responsibility, guaranteed gain, or a sample median as a prescribed cast count. Raid Guide has no rotation, talent, gear, phase-strategy, or prescriptive-advice field.

`locale` accepts only `zh-CN` or `en`; `status` accepts only `anomaly`, `review`, `ok`, or `unverified`; `tone` accepts only `danger`, `warn`, `ok`, or `info`. `boss_percentage` may be `null`.

Callers cannot submit HTML, CSS, or JavaScript, and unknown fields are rejected. Each Mechanic Review mechanic stores at most 20 display events. An event `evidence_excerpt` accepts only the flat scalar fields `event_type`, `ability_id`, `source_id`, `target_id`, `amount`, `duration_ms`, `delta_ms`, `episode`, `outcome`, and `note`; text values are limited to 300 characters. It cannot embed a raw event object or complete Mechanic Evidence Set. An `anomaly` status requires a positive failure count and display events; `ok` requires zero failures; `unverified` cannot claim success or failure counts. A Report Document has no `judgment` or `causal_attribution` field.

The renderer trust boundary extends beyond path and file SHA-256 checks. Every source must be valid UTF-8 JSON matching its declared artifact kind and current schema. Encounter Benchmark and Guide Snapshot canonical content IDs are verified, the Guide Snapshot Markdown hash is verified, and Personal Analysis is recomputed from its Complete Bundle and Report Index. The renderer then cross-checks every claimed Report Revision, Boss Attempt, actor/player, comparison hard condition, Benchmark sample count and confidence, Snapshot ID, Profile ID, and chapter isolation. A Mechanic Review source must pass the strict schema above and record terminated pagination plus a Report Revision check before and after collection; the renderer cross-checks its identity, ruleset, counts, conclusions, phases, and minimal excerpts. Persisting the Report Document still cannot persist the complete Mechanic Evidence Set. HTML states that a Complete Bundle or hard-condition match was verified only after those checks establish it. Plain SHA-256 still provides local content identity and corruption detection, not producer authentication.

`coach guide-report` is the CLI Raid Guide assembly path. It accepts exactly one validated Guide Snapshot JSON artifact and no caller-retyped chapters. The derived document preserves the exact Snapshot ID and artifact file SHA-256, then copies encounter identity, `benchmark_id`, Profile IDs, sample count/confidence, metrics, localized abilities, mechanic anchors, and sources within their original chapters. Every chapter is checked against that same Snapshot chapter, preventing equal-valued metrics, abilities, or sources from being exchanged across Bosses.

`coach personal-workflow-init <WCL_URL_WITH_NUMERIC_FIGHT_AND_SOURCE>` is the timing entry point run immediately after selection. It accepts only the selected WCL Report, Boss Attempt, and player identity, reads no Analysis, Complete Bundle, Ranking Cohort, or Profile, and persists `selected_identity` with the monotonic/wall-clock origin in a canonical registered workflow. Later `coach personal-workflow` calls must continue the initial or latest workflow through `--previous-workflow`. Personal Analysis report code, fight ID, and actor ID must match `selected_identity`; the Cohort and both Profiles then bind to the Analysis hard-condition identity.

`coach personal-workflow` is the Agent's repeatable Personal Review acquisition/reuse control point. Its content-addressed schema `2` artifact uses an internal monotonic clock for one origin, cumulative elapsed, and generated stage timings; the public CLI has no raw timing parameters. A workflow is written atomically at `outputs/personal-workflows/<workflow_id>.json` and registered in its artifact index; `--previous-workflow` must match that canonical path, file identity, and index, and arbitrary external paths are rejected. These checks prevent accidental arbitrary-path use and detect corruption, but SHA-256 is content identity rather than producer authentication and cannot resist a local process that can edit both the artifact and index. A previous workflow restores stable candidate identities plus a validated Benchmark, Reference Sample, and checkpoint/progress hash references. A Ranking Cohort retains the complete deduplicated final queried page and records the actual page range, remote `hasMorePages`, `target_reached`, and `exhausted`, so an identity after a rejected candidate on that page can be consumed without refetching. Timing continuity requires monotonic non-regression and a current wall-minus-monotonic baseline within the persisted baseline's recorded tolerance; the session marker is persisted metadata for local diagnostics only, not a strict equality check. If continuity cannot be established, progress is retained while `timing_continuity_unavailable` stops optional acquisition. The CLI checks a 20-second reserve before each optional operation; in-flight work may overrun. An API failure records its blocker and existing progress and stops optional scheduling. The 30-second reuse target applies only after the Benchmark's Cohort ID exactly matches and every Reference Sample can be recomputed from Complete Bundle evidence to rebuild the exact Benchmark; otherwise the target is 180 seconds. The 180/30-second measurement is trustworthy only within a cooperative local workspace and does not measure the WCL network. Candidate exhaustion becomes `ranking_page_exhausted` only when Cohort pagination metadata proves a terminal page, and otherwise becomes `ranking_cohort_refresh_required`. An unavailable target Personal Analysis or Complete Bundle yields `blocked` without claiming a Personal Analysis artifact or report availability.

`coach personal-report <PERSONAL_ANALYSIS> <ENCOUNTER_BENCHMARK> <COMPARISON> --workflow <COMPARISON_READY_WORKFLOW> ...` is the comparison-ready path. `coach personal-report <PERSONAL_ANALYSIS> --workflow <PARTIAL_READY_WORKFLOW> --encounter-profile <PROFILE> --specialization-profile <PROFILE> ...` is the partial path. `--workflow` is a required source for the assembler, renderer, and formal Personal Review delivery; there is no artifact-only completed-delivery path. At assembly, rendering, and delivery, the full path separately rereads the workflow-bound Cohort, Profiles, Benchmark, and every Reference Sample Complete Bundle snapshot, checks file hashes, and rebuilds the exact Benchmark through `verify_benchmark_for_cohort`. Both workflow paths finalize only after HTML/index exists and return a content-addressed delivery artifact, status, elapsed, and `target_met`; elapsed starts at the selected workflow origin and covers validation, locks, persistence, and rendering. Timing explicitly records `clock_source: "local_monotonic_and_wall_clock"` and `wcl_network_measurement: "not_measured"`; deterministic injected clocks in tests validate state only and do not represent actual local wall-clock elapsed time. Delivery/finalization failure never returns delivered; an immutable content-addressed delivery that was already written remains as an orphan so no concurrent report loses a referenced artifact. A content-addressed artifact is reused only when its canonical file bytes and SHA-256 match exactly; parsed JSON equality with different bytes still refuses overwrite. The partial path deeply revalidates the workflow, Cohort, Reference Samples, player Analysis, and both Profiles and derives the sample count from evidence; it accepts neither Benchmark/Comparison nor a caller-entered count. Advice schema `2` uses the same finite vocabulary, and a fact source unavailable in the current mode returns `invalid_input`. Advice is never overwritten or deleted after it is written; assembly/render failure may leave an unreferenced content-addressed orphan safely in place, to be reclaimed only by an explicit cleanup process based on references and retention policy.

Advice names Spells only by client ability ID greater than one. Every value in an Advice item's `ability_ids`, including when the action has no ability ID, must bind to the same ability declared as `action_type: "player_cast"` by the Specialization Profile. An event-supported ability action must also cite a direct-player `player_cast`/`key_action` metric for that same ID. Per-ability owned aggregate damage/healing and `automatic`, `internal`, or `owned_actor` events remain audit-only and cannot support recommendations. General advice without an ability ID remains valid. English rendering uses the same Report Index's WCL name. Chinese rendering requires a validated zhCN SpellName mapping hit and stops with a structured error when it is unavailable. Advice and Report renderers apply the same public HTTP(S), no-userinfo, and credential-query URL validation. Validation establishes reference, value, source, and identity consistency; the finite contract prevents responsibility, causality, guaranteed-gain, and median-prescription fields but is not natural-language semantic review.

The SHA-256 of validated canonical compact UTF-8 JSON is the `document_id`. Renderer schema `1` produces self-contained HTML with no external resources; the filename is the SHA-256 of the final UTF-8 HTML bytes. HTML and its JSON index are stored as `outputs/reports/<html-sha256>.html` and the matching `.json`. Existing content is reused and never overwritten when its identity or hash differs. The JSON index records the canonical Report Document, source artifacts, renderer schema, and HTML hash.

Persisting a Report Document does not make a Mechanic Evidence Set persistent. Only Agent-selected conclusions, counts, and minimal evidence excerpts may be saved, never the complete filtered event range.

Ranking Cohort pagination `first_page` and `last_page` values must be positive integers with `first_page <= last_page`. `exhausted: true` requires an explicit valid page range, `has_more_pages: false`, and `truncated: false`; metadata missing any of those fields cannot prove candidate exhaustion. When the remote has no more pages and local results are not truncated, `exhausted: false` is invalid. Any next/resume page metadata must agree, point beyond the queried range, and not coexist with exhaustion.

Personal Review assembly, rendering, and delivery must validate the same `outputs/personal-workflows` registry and index under the exact data root configured by the CLI; merely residing in any directory named `personal-workflows` establishes no provenance. This remains a cooperative local trust model and cannot resist a local process that can modify artifacts and the index inside the configured data root.

## Coaching Artifacts

Personal Reviews, Benchmarks, and Guides consume only Complete Bundles that pass the integrity rules above. They cannot rewrite a Report Index, Fight Bundle, or Canonical Event. Mechanic Review is the non-persistent exception and consumes only its process-local Mechanic Evidence Set.

- `profiles/` stores declarative Specialization Profiles and Encounter Profiles. Profile identity includes game version and ranking partition; an Encounter Profile also includes encounter and difficulty. Optional Specialization ability `action_type` accepts only `player_cast`, `automatic`, `internal`, or `owned_actor`; an undeclared ability is not a key action. Non-empty Encounter eligibility target lists require `target_id_type: "npc_game_id"`; targets are distinct positive NPC gameIDs across both lists, never report-local actor IDs. The Profile ID is the SHA-256 of validated canonical JSON.
- `cohorts/` stores a Ranking Cohort for exactly one encounter, difficulty, class, specialization, and partition. Ranking Candidate rank and non-null score values must be finite, non-boolean JSON numbers; canonical Cohort JSON accepts no `NaN` or infinity values. `cohort_id` is the SHA-256 of canonical JSON excluding the ID itself. A Ranking Candidate becomes a Reference Sample only after Complete Bundle, hard-condition, and Encounter Profile eligibility checks pass.
- An Encounter Benchmark aggregates 3 to 10 unique Reference Samples from one Ranking Cohort. Its `sample_count` must be an integer exactly equal to the `reference_samples` length, and it records the exact `cohort_id`. `benchmark_id` is the SHA-256 of canonical JSON excluding the ID itself. Different Encounter Designators require different benchmarks.
- `tasks/` stores Coach Request Manifests. Partial work retains each encounter's blocker and artifact references.
- `guides/` stores immutable Guide Snapshots. Every chapter records the exact `benchmark_id` and chapter-local ability metrics localized by ability ID; a snapshot may reference multiple Encounter Benchmarks but cannot overwrite an older snapshot.

A Personal Analysis at schema `4` records Report Revision, fight ID, actor ID, comparison hard conditions, and separates direct-player, owned-actor, and synthetic casts. Its ranking-partition game version rules remain unchanged. Comparison fails unless Analysis and Benchmark game version, encounter, difficulty, class, specialization, and partition match exactly.

Older Personal Analysis, Encounter Benchmark, and Comparison schemas are rejected; rerun their commands to produce schemas `4`/`3`/`3`. Migrate an older Profile that uses report-local target IDs to `npc_game_id`, then rebuild its downstream artifacts. Rebuilding is offline when all required Complete Bundles, Report Indices, Profiles, and ability-name mappings already exist locally; missing Reference Sample data or mappings must still be prepared online.

Coaching Artifacts are supported only when this CLI generates and consumes them in the user's local data or work directory. Plain SHA-256 does not authenticate a producer; externally supplied Artifacts must not be treated as trusted input. Complete Bundles, Ranking Cohorts, Personal Reviews, Encounter Benchmarks, and Guide Snapshots from the former HMAC schemas are incompatible and must be rebuilt.

## Personal Review Timing Boundary

Immediately after Boss Attempt and player selection, run `coach personal-workflow-init` before target Complete Bundle retrieval, Ranking Candidate discovery, and Profile retrieval/synthesis. Later calls inherit the same origin through `--previous-workflow`, so conservative wall time covers that work plus out-of-process Agent synthesis, validation, rendering, and HTML delivery. Standard candidate acquisition collects at most 10 samples, and all 3 to 10 available qualified Reference Samples remain in the workflow and Benchmark. `stage_progress.retrieval` is `in_progress` while candidate, Profile, or player evidence is incomplete; Agent synthesis is `unavailable` before it can be observed and `in_progress` once the player and Profiles are ready. Delivery/finalization records it as `unavailable` because its separate duration cannot be observed, so final `target_met` remains `null`. The public CLI accepts no raw timing.
