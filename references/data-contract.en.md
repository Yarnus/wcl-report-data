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

## Report Document

A Report Document is presentation input, not evidence-layer data. Schema `1` accepts `document_type: "mechanic_review"`, `"personal_review"`, or `"raid_guide"`. All three share locale, title, subtitle, source artifacts, and an audit-boundary note; all other fields are strictly type-specific.

The complete input shape follows. `phases`, each mechanic's `events`, and `actions` may be empty arrays:

```json
{
  "schema_version": 1,
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

A `personal_review` has exactly the shared fields plus `identity`, `player`, `comparison`, `metrics`, and `abilities`. Its `identity` uses the same Boss Attempt shape as Mechanic Review, and its sources must include both `personal_analysis` and `encounter_benchmark`.

- `player`: `name`, `class_name`, `spec_name`, nullable `item_level`, and boolean `anonymous`.
- `comparison`: the complete comparison hard conditions `game_version`, `partition_id`, `encounter_id`, `difficulty_id`, `class_name`, and `spec_name`, plus `sample_count` of at least 3 and `confidence` of `low` or `normal`. IDs are positive, and class/spec must match `player`.
- `metrics`: non-negative integer `damage_total`, `healing_total`, `interrupts`, `deaths`, and `resource_events`, plus nullable finite `damage_total_delta`.
- `abilities`: at most 100 entries containing `name`, non-negative integer `player_casts`, and nullable non-negative finite `median_casts`, `player_first_cast_ms`, and `median_first_cast_ms`.

A `raid_guide` has exactly the shared fields plus `identity`, `specialization`, `snapshot_id`, `ability_names_build`, and `chapters`; its sole source kind is `guide_snapshot`. Its `identity` contains `game_version`, positive `partition_id`, `difficulty_name`, `class_name`, and `spec_name`. The `snapshot_id` and both Profile IDs in each chapter must be SHA-256 digests.

- `chapters`: 1 to 20 chapters with unique encounter IDs. Each contains `encounter_id`, `encounter_name`, `sample_count` of at least 3, `confidence`, nullable `damage_total_median`, `abilities`, `target_damage`, `mechanic_anchors`, both Profile IDs, and `sources`.
- Chapter `abilities` retain only ability name, median casts, and median first-cast time; `target_damage` retains only numeric target ID and median damage; `mechanic_anchors` retain only name and nullable observed time.
- Chapter `sources` accept only an `encounter` or `specialization` kind, title, public HTTP(S) URL, and quote summary. Ruleset and chapter source URL authorities cannot contain user information. Query-string and fragment parameter names cannot be credential, key, token, authentication, or signature names after case, common separators, and percent encoding are normalized.

Personal Review has no mechanic-attribution or recommendation field. Raid Guide has no rotation, talent, gear, phase-strategy, or prescriptive-advice field. Callers must not use titles, summaries, or `scope_note` to describe a damage delta as achievable improvement or a sample median as a recommendation.

`locale` accepts only `zh-CN` or `en`; `status` accepts only `anomaly`, `review`, `ok`, or `unverified`; `tone` accepts only `danger`, `warn`, `ok`, or `info`. `boss_percentage` may be `null`.

Callers cannot submit HTML, CSS, or JavaScript, and unknown fields are rejected. Each Mechanic Review mechanic stores at most 20 display events. An event `evidence_excerpt` accepts only the flat scalar fields `event_type`, `ability_id`, `source_id`, `target_id`, `amount`, `duration_ms`, `delta_ms`, `episode`, `outcome`, and `note`; text values are limited to 300 characters. It cannot embed a raw event object or complete Mechanic Evidence Set. An `anomaly` status requires a positive failure count and display events; `ok` requires zero failures; `unverified` cannot claim success or failure counts. A Report Document has no `judgment` or `causal_attribution` field. The renderer verifies that every source artifact exists and matches its declared SHA-256.

The SHA-256 of validated canonical compact UTF-8 JSON is the `document_id`. Renderer schema `1` produces self-contained HTML with no external resources; the filename is the SHA-256 of the final UTF-8 HTML bytes. HTML and its JSON index are stored as `outputs/reports/<html-sha256>.html` and the matching `.json`. Existing content is reused and never overwritten when its identity or hash differs. The JSON index records the canonical Report Document, source artifacts, renderer schema, and HTML hash.

Persisting a Report Document does not make a Mechanic Evidence Set persistent. Only Agent-selected conclusions, counts, and minimal evidence excerpts may be saved, never the complete filtered event range.

## Coaching Artifacts

Personal Reviews, Benchmarks, and Guides consume only Complete Bundles that pass the integrity rules above. They cannot rewrite a Report Index, Fight Bundle, or Canonical Event. Mechanic Review is the non-persistent exception and consumes only its process-local Mechanic Evidence Set.

- `profiles/` stores declarative Specialization Profiles and Encounter Profiles. Profile identity includes game version and ranking partition; an Encounter Profile also includes encounter and difficulty. The Profile ID is the SHA-256 of validated canonical JSON.
- `cohorts/` stores a Ranking Cohort for exactly one encounter, difficulty, class, specialization, and partition. `cohort_id` is the SHA-256 of canonical JSON excluding the ID itself. A Ranking Candidate becomes a Reference Sample only after Complete Bundle, hard-condition, and Encounter Profile eligibility checks pass.
- An Encounter Benchmark aggregates at least three unique Reference Samples from one Ranking Cohort and records the exact `cohort_id`. `benchmark_id` is the SHA-256 of canonical JSON excluding the ID itself. Different Encounter Designators require different benchmarks.
- `tasks/` stores Coach Request Manifests. Partial work retains each encounter's blocker and artifact references.
- `guides/` stores immutable Guide Snapshots. Every chapter records the exact `benchmark_id`; a snapshot may reference multiple Encounter Benchmarks but cannot overwrite an older snapshot.

A Personal Review analysis records Report Revision, fight ID, actor ID, and comparison hard conditions. The comparison identity `game_version` uses the selected ranking partition's `compactName` from the same Report Index, falling back to that partition's `name`; it never uses the numeric WCL `masterData.gameVersion` product ID. Comparison fails unless analysis and benchmark game version, encounter, difficulty, class, specialization, and partition match exactly.

Coaching Artifacts are supported only when this CLI generates and consumes them in the user's local data or work directory. Plain SHA-256 does not authenticate a producer; externally supplied Artifacts must not be treated as trusted input. Complete Bundles, Ranking Cohorts, Personal Reviews, Encounter Benchmarks, and Guide Snapshots from the former HMAC schemas are incompatible and must be rebuilt.
