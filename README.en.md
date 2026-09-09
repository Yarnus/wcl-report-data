# wcl-raid-coach

<p align="center">
  <img src="assets/timewarp-inn-dog.svg" width="220" alt="Original fantasy icon of a golden dog guarding a timewarp inn">
</p>

`wcl-raid-coach` is a platform-neutral, self-contained Agent Skill and Python 3.11+ package for preparing Retail Warcraft Logs raid evidence, reviewing encounter mechanics and personal performance, and generating Boss guides from ranked references.

It uses only the official Warcraft Logs OAuth and GraphQL APIs; it does not scrape report pages.

Personal Reviews and guides use Report Revision-safe Complete Bundles. Mechanic Review uses an equally revision-isolated, non-persistent Mechanic Evidence Set.

[Chinese documentation](README.md)

## Scope

- Supports Retail raid reports; Classic and Mythic+ are out of scope. If one WCL Report contains both raid and Mythic+ fights, only its raid Boss Attempts are listed and prepared.
- Supports public and unlisted reports; private reports requiring user OAuth are not supported.
- Accepts report URLs from `warcraftlogs.com`, `www.warcraftlogs.com`, and `cn.warcraftlogs.com`.
- CN report URLs are normalized to the global site; API requests still use the official global WCL endpoints.
- Runtime code uses only the Python standard library.
- Mechanic Review currently covers all eight official raid encounters in The Venomous Abyss on Normal, Heroic, and Mythic; it excludes the Nymrissa Wavecaller world boss.

## Quick Start

Requirements: Python 3.11 or newer, network access to `warcraftlogs.com`, and a Warcraft Logs API v2 client ID and client secret.

After installing the Agent Skill, ask "How do I use wcl-report-data?" to see its capability menu, or start a task directly in natural language:

- "Show me the Boss Attempts and participants in this WCL Report: `<WCL_URL>`"
- "Review the mechanic handling in this Boss Attempt: `<WCL_URL_WITH_NUMERIC_FIGHT>`"
- "Review my performance in this Boss Attempt as `<character>`: `<WCL_URL_WITH_NUMERIC_FIGHT>`"
- "Give me an Unholy Death Knight guide for the current raid's H7 and H8."

Run the CLI from the repository root. When using an installed Skill, an Agent locates the Skill root containing `SKILL.md` and uses it as the working directory for the bundled CLI; no global Python package installation is required:

```bash
python -m wcl_raid_coach doctor
```

After `wcl_api` reports `reachable`, create a report index:

```bash
python -m wcl_raid_coach inspect "https://www.warcraftlogs.com/reports/<code>"
```

Resolve a general guide request for Unholy Death Knight on the current raid's H7/H8:

```bash
python -m wcl_raid_coach coach resolve --spec "Unholy DK" --encounter H7 --encounter H8
```

This only resolves current-raid context and creates a task awaiting confirmation. See [the Skill instructions](SKILL.md) for the complete workflow.

Review one explicit Boss Attempt in real time:

```bash
python -m wcl_raid_coach coach mechanics \
  "https://www.warcraftlogs.com/reports/<code>#fight=12"
```

A bare report URL never selects a Boss Attempt automatically. Use an Encounter Designator to filter choices, then put the chosen numeric fight in the URL:

```bash
python -m wcl_raid_coach coach mechanics \
  "https://www.warcraftlogs.com/reports/<code>" --encounter H2
```

Mechanic Review accepts kills and wipes, but only completed Boss Attempts; it rejects `fight=last`.

For a fast conversational mechanic check, request compact output. It retains mechanic counts and player anomalies, removes raw WCL payloads, summarizes pet/NPC noise, and caps expanded player anomalies per mechanic:

```bash
python -m wcl_raid_coach coach mechanics \
  "https://www.warcraftlogs.com/reports/<code>#fight=12" --compact
```

To inspect one or more participants' death chain around an anomaly without first preparing a full-attempt Complete Bundle, collect a fight-relative event window:

```bash
python -m wcl_raid_coach coach evidence \
  "https://www.warcraftlogs.com/reports/<code>#fight=12" \
  --at-ms 210472 --window-ms 10000 --player-id 17 \
  --expected-identity JKy1tpWXjw2rBYZm:17:22
```

`--expected-identity` must be copied verbatim from the compact Mechanic Review's `evidence_identity`, preventing the stages from crossing a WCL Report, Report Revision, or Boss Attempt. A Focused Evidence Window accepts at most three participants sharing one anomaly time; different times require separate calls. It fully paginates each participant and returns referenced actor and ability names. Stdout contains at most 200 events, prioritizing deaths and resurrections before facts nearest the anchor; `evidence` reports truncation and the complete matched count. It remains process-local, creates no Report Index, Raw Page, Fight Bundle, Complete Bundle, Canonical Event, manifest, or checkpoint, and does not establish responsibility or wipe causality.

For a formal Mechanic Review delivery, add `--report` to the same command; select `--locale zh-CN` (the default) or `--locale en`:

```bash
python -m wcl_raid_coach coach mechanics \
  "https://www.warcraftlogs.com/reports/<code>#fight=12" --report --locale en
```

Only after the in-memory Mechanic Review completes pagination and verifies the same Report Revision before and after collection, this path writes a strictly sanitized source to `outputs/mechanic-reviews/<sha256>.json`, assembles and validates its Report Document from that source, and renders into `outputs/reports/`. JSON stdout returns `source.path`, `source.sha256`, the `document`, and content identities and paths under `report`; no mixed output needs scraping. The source retains only WCL Report, Report Revision, Boss Attempt, and Mechanic Ruleset identity and metadata, counts, supported conclusions, phases, participants, and flat minimal evidence excerpts. It omits the complete filtered event range, Raw Pages, Fight Bundles, `raw_event`, `raw_events`, aura application objects, arbitrary WCL payloads, responsibility, and wipe causality. Pagination, revision, collection, sanitization, validation, or initial rendering failure leaves no new source artifact; identical content reuses the existing immutable artifact.

Other already-assembled Report Document types can still be rendered separately according to the [dataset contract](references/data-contract.en.md). This command does not access WCL or require credentials:

```bash
python -m wcl_raid_coach coach render "<WORK_DIR>/report.document.json"
```

A Raid Guide does not require the caller to rewrite a Report Document. Pass the single Guide Snapshot JSON path returned by `coach guide` to the CLI assembler, which validates the Snapshot and Markdown identities, derives the complete document chapter by chapter, and renders it immediately:

```bash
python -m wcl_raid_coach coach guide-report "<DATA_ROOT>/guides/<SNAPSHOT_ID>.json"
```

A Personal Review likewise requires no retyped metrics or identity. Formal delivery requires the three JSON artifacts produced by `coach review`, `coach benchmark`, and `coach compare` together with a canonical comparison-ready `--workflow`. The CLI finalizes delivery after the HTML/index and provides no formal Personal Review path that bypasses the workflow:

```bash
python -m wcl_raid_coach coach personal-report \
  "<WORK_DIR>/personal-analysis.json" \
  "<WORK_DIR>/encounter-benchmark.json" \
  "<WORK_DIR>/comparison.json" \
  --workflow "<DATA_ROOT>/outputs/personal-workflows/<WORKFLOW_ID>.json" \
  --advice "<WORK_DIR>/advice-draft.json" \
  --encounter-profile "<WORK_DIR>/encounter-profile.json" \
  --specialization-profile "<WORK_DIR>/specialization-profile.json" \
  --locale en
```

Timing starts immediately after Boss Attempt and player selection, before target Complete Bundle retrieval, Ranking Candidate discovery, and Profile retrieval/synthesis: run `coach personal-workflow-init "<WCL_URL>#fight=<FIGHT_ID>&source=<ACTOR_ID>"` to create a canonical blocked workflow. This command needs only the selected WCL Report, Boss Attempt, and player identity, with no Analysis, Complete Bundle, Ranking Cohort, or Profile. Every later `coach personal-workflow` invocation must pass the initial or latest workflow as `--previous-workflow` and supply the Analysis, Cohort, and both Profiles; the CLI binds them to the initialized identity. The monotonic origin and conservative wall time between invocations cover candidate discovery, Profile and Agent synthesis, retrieval, validation, rendering, and delivery. Standard candidate acquisition provides at most 10 qualified Reference Samples, and all available samples from 3 through 10 are retained.

Workflow `retrieval` is `in_progress` while candidate, Profile, or player evidence is incomplete. Agent synthesis is `unavailable` before it can be observed and `in_progress` once the player and Profiles are ready; delivery/finalization records it as `unavailable` because its separate duration cannot be measured. Final `target_met` therefore remains `null`, while total elapsed still covers the work.

Personal Review reuses an Encounter Benchmark only when it is bound to the current Ranking Cohort and can be fully rebuilt from every Reference Sample's Complete Bundle evidence. All 3 to 10 available qualified samples are immediately deliverable; do not wait or continue acquisition merely to reach 10. Three to nine samples have low confidence, while 10 has normal confidence. The workflow records exact Cohort, Profile, Benchmark, and per-Reference-Sample manifest/Report Index paths and file hashes. Full-report assembly, rendering, and delivery each reread those snapshots and run the same deep rebuild check; any evidence change rejects delivery. `coach personal-workflow` records elapsed and stage timings from an internal monotonic clock; the public CLI has no raw timing parameters. Repeated calls use `--previous-workflow` to retain the timer origin, session marker, validated Benchmark, and stable candidate progress. A previous workflow must use canonical `outputs/personal-workflows/<workflow_id>.json`, match its content identity, and be registered in its artifact index; arbitrary external paths are rejected. The path, index, and hash prevent accidental arbitrary-path use and detect corruption, but do not authenticate a producer or resist a local process that can edit both the artifact and index. `coach personal-report --workflow` returns and persists a content-addressed delivery finalization whose elapsed time runs from workflow selection through HTML/index hash verification and delivery artifact persistence; `target_met` and `completion_status` come from that record. A content-addressed Artifact is reused only when its canonical file bytes and SHA-256 match exactly; parsed-object equivalence with different bytes still rejects overwrite. Finalization failure never returns delivered; an immutable content-addressed delivery that was already written remains as an orphan so another concurrent report can never lose a referenced artifact. Deeply validated reuse selects the 30-second target; all other work selects the 180-second target. The CLI reserves 20 seconds before scheduling each optional operation. The 180/30-second measurement is trustworthy only within a cooperative local workspace and records `wcl_network_measurement: "not_measured"`; an in-flight WCL request or rate-limit wait cannot be cancelled, may cross the soft target, and is reflected by the next workflow invocation.

Timing continuity requires monotonic non-regression and a current wall-minus-monotonic baseline within the persisted baseline's tolerance. If continuity cannot be established, progress is retained while optional acquisition and continuous timing stop. The persisted session marker is local diagnostic metadata only, not a strict equality check.

Each rejection names a stable candidate identity from the Ranking Cohort; progress is never inferred from counts. When `coach candidates` reaches its goal, it retains the complete deduplicated final queried page so later workflow calls can consume remaining candidates from that page. Pagination records the actual queried page range, remote `hasMorePages`, `target_reached`, and `exhausted`. Page exhaustion is claimed only when this metadata proves a terminal page; otherwise exhausted local entries require a refreshed Cohort. When budget, proven page exhaustion, or API failure leaves fewer than 3 qualified samples, run `coach personal-report <ANALYSIS> --workflow <PARTIAL_READY_WORKFLOW> --encounter-profile <PROFILE> --specialization-profile <PROFILE> [--advice <DRAFT>]`. The report derives its count by revalidating the workflow, Cohort, and Reference Sample evidence and accepts no caller-entered count. An incomplete player Complete Bundle produces only a `blocked` workflow; `--progress <CHECKPOINT>` preserves path/hash progress without producing a report or claiming a Complete Bundle.

This command revalidates Personal Analysis schema `4`, Encounter Benchmark schema `3`, and Comparison schema `3`. `--advice` is optional; when present, both Profile paths are required. Coaching Advice schema `2` accepts no free-form action, condition, or verification prose: a finite structured vocabulary is rendered by the CLI for `zh-CN` or `en`, so responsibility, causality, guaranteed gain, and median-as-prescription claims have no validated Advice field. This is a structural boundary, not natural-language semantic review. Every action with an ability ID requires that ability to be declared as `action_type: "player_cast"` by the Specialization Profile. An event-supported ability action must also cite a direct-player `player_cast`/`key_action` metric for the same ability ID; owned aggregate damage/healing remains audit-only and cannot support a recommendation. Personal Review currently has no Mechanic Review source, so mechanics Advice can only be conditional experience-based guidance backed by a current Profile. The CLI also verifies fact values plus local Profile paths, file hashes, Profile IDs, and source entries. Advice is immutable once written; downstream assembly or rendering failure may leave a safely reusable content-addressed orphan artifact.

Advice references Spells by ability ID. Chinese output requires a validated zhCN SpellName mapping hit and returns a structured error when one is unavailable; it never invents translations. A Specialization Profile produces `key_action_*` only for an ability explicitly declared with `action_type: "player_cast"`; a zero median is retained when every Reference Sample has zero casts. Undeclared abilities and `automatic`, `internal`, or `owned_actor` abilities are excluded, and WCL synthetic Melee ID `1` cannot be declared as a player action. Key-action display never falls back to raw `casts_median`, which retains pet and internal audit facts.

Non-empty Encounter Profile `priority_target_ids` and `excluded_target_ids` require `target_id_type: "npc_game_id"`. A report-local actor ID cannot be compared across WCL Reports; rebuild the Profile, Benchmark, and Comparison using NPC `gameID` values from each Report Index. Rebuilding can run offline when the local Complete Bundles, Report Indices, Profiles, and ability-name mapping already exist; missing Reference Sample data or Chinese mappings must be prepared online first. Personal Review retains totals and displays both durations, per-minute damage/healing, and valid Reference Sample denominators. Normalization does not correct survival, downtime, phases, talents, gear, or assignments, and sample medians are not prescribed actions. Numbers appear only in structured fact references. Advice and Report renderers apply the same public HTTP(S), no-userinfo, and credential-query URL validation.

The CLI returns the derived `document` and report paths/content identities; with advice it also returns `advice.path`, `advice.sha256`, and `advice.advice_id`. HTML has no external resources. Personal Review always expands Output, Survival, Mechanics, and Team Contribution. Each dimension colocates available facts/comparisons, improvement advice, applicability conditions, a next-Boss-Attempt verification goal, and evidence/limits; full comparison details remain afterward. Missing advice, unassessed dimensions, missing Chinese SpellNames, and insufficient Reference Samples never produce filler conclusions: the applicable location explicitly says Not Evaluated or rejects Advice that requires an unverified Chinese name. The renderer reparses and cross-checks every source. Personal Review advice cannot assert an unverified cause, responsibility, guaranteed gain, or a sample median as a prescribed cast count. Only Report Document schema `2` is accepted now. Existing schema `1` static HTML remains viewable, but schema `1` cannot be rerendered; rerun `personal-report` from current Analysis, Benchmark, and Comparison source artifacts first.

Prepare the fight selected in the URL:

```bash
python -m wcl_raid_coach prepare "https://www.warcraftlogs.com/reports/<code>#fight=12"
```

You can also prepare explicit fights or all completed attempts for an encounter:

```bash
python -m wcl_raid_coach prepare "https://www.warcraftlogs.com/reports/<code>" --fight 12 --fight 15
python -m wcl_raid_coach prepare "https://www.warcraftlogs.com/reports/<code>" --encounter 3129
```

Use the returned manifest to query events without loading the entire event stream into a model context:

```bash
python -m wcl_raid_coach query \
  "<DATA_ROOT>/reports/<code>/revisions/<revision>/fights/12/manifest.json" \
  --type damage --target-id 17 --limit 200
```

The CLI always writes JSON to standard output, including structured domain errors. See `python -m wcl_raid_coach --help` for all arguments and [the Skill instructions](SKILL.md) for the complete workflow.

`coach review`, `coach benchmark`, `coach guide`, `coach compare`, and `coach personal-report` consume only local Artifacts. The current path uses Personal Analysis `4`, Encounter Benchmark `3`, and Comparison `3`; older schemas must be regenerated. Commands that access WCL still require OAuth client credentials.

## Encounter Designators And Name Mappings

The Agent entrypoint loads [mechanics/triage](references/workflow-mechanics.en.md), [Personal Review](references/workflow-personal.en.md), and [guides](references/workflow-guide.en.md) on demand. Personal Review initializes timing before searching compatible local Benchmarks with their bound original Cohorts/Profiles, then deeply validates reuse of existing three-to-ten samples. Multi-Boss guides reuse current shared Specialization Profiles and eligible completed chapters, acquiring only missing work. Detailed fields and provenance rules are read from the data contract when needed.

External guides follow [bounded retrieval](references/guide-retrieval.en.md): one failed WebFetch attempt leads to local curl, then an available browser and version-relevant alternatives. HTTP 200 still requires actual article verification; challenges, script shells, search snippets and generic Blizzard class overviews cannot substitute for specialization guides. Disclose evidence gaps when tools, article content or patch relevance cannot be verified.

For priority candidates, run `python -m wcl_raid_coach coach triage "<WCL_URL_WITH_NUMERIC_FIGHT>"`. One process reuses its client and report metadata, returning compact `mechanics`, ordered `candidates`, `windows`, and `coverage`. Only verified/enabled/target player anomalies qualify, with at most three players and three distinct anomaly times per player. Only players in the same anomaly share a window. A missing ten-second pre-death interval triggers one supplemental death window. No supported candidate returns `no_supported_candidate` without focused requests. Team facts remain tied; judgment/causal_attribution are null. Evidence remains in memory, with Report Revision checks across phases; failure never returns a successful combined result. Coverage discloses suppressed compact anomaly records and truncated windows. This is not a Personal Review.

The Skill understands Encounter Designators such as `PT6`, `H6`, and `M6`. The prefixes mean Normal, Heroic, and Mythic; the number is the one-based position in WCL's original `zone.encounters` list. A designator identifies only a difficulty and encounter. When a report has multiple matching Boss Attempts, the Skill lists explicit fight IDs and waits for a choice instead of selecting a kill, the latest attempt, or every attempt.

`inspect`, `prepare`, and `query` do not download display mappings or return `ability_names`. `inspect` uses a valid existing content mapping; when absent or corrupt, it displays original WCL names and returns `content_names: null`. With explicit numeric fight selections, run prepare directly; multiple selections in one WCL Report can use `prepare "<WCL_URL>" --fight 1 --fight 3` and share one report metadata query.

For outputs needing names, such as Guide generation, the CLI downloads the current Retail zhCN `SpellName` CSV from Wago Tools and creates a complete `ability-names.zhCN.json` plus metadata in the data directory. A valid existing JSON is reused without network access. A mapping may be used only when the ID also occurs in the Report Index `abilities[].gameID`. Chinese Guide and Skill user-facing text must use the mapped Chinese SpellName and must not translate names ad hoc; final guide generation stops when a mechanic Spell ID has no Chinese mapping. Chinese names are current-client display enrichment and do not modify the Report Index. Mechanic Review does not initialize this local mapping; it uses the Chinese and English mechanic names shipped in the versioned Mechanic Ruleset.

The CLI separately maintains `content-names.zhCN.json`, generated from `Map`, `DungeonEncounter`, `JournalEncounter`, and `JournalEncounterCreature` tables from one Wago client build. Its scope is limited to the current raid on Normal, Heroic, and Mythic plus the configured eight Mythic+ maps. Original WCL English names and IDs remain audit data. Wago does not provide a reliable direct link to WCL NPC `gameID`, so localized NPC names are encounter-scoped display enrichment and cannot be used as event identity.

## Credentials

A typical user only needs to provide these canonical variables through the Agent host's private environment configuration:

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

The CLI temporarily accepts the paired aliases `WCL_ID` and `WCL_SECRET`. It does not automatically read `.env` from the current directory or `/workspace`. To use a credential file, pass it explicitly and put the global option before the subcommand:

```bash
python -m wcl_raid_coach --env-file "<WORKSPACE>/.env" doctor
python -m wcl_raid_coach --env-file "<WORKSPACE>/.env" inspect "<WCL_URL>"
```

Never ask a user to paste a secret into chat, never overwrite an existing credential file, and never print a client secret or access token. See [the setup guide](references/setup.en.md) for lookup order and storage paths.

## Storage Layout

Typical users do not configure storage paths. Global `--data-root` and `--cache-root` options take precedence, followed by the optional `WCL_RAID_COACH_HOME` and `WCL_RAID_COACH_CACHE` variables. Without an override, an existing persistent `/workspace` is a compatibility fallback for cloud Agent sandboxes. Otherwise local Unix/macOS uses `~/.local/share/wcl-raid-coach/` and `~/.cache/wcl-raid-coach/`; Windows uses `%LOCALAPPDATA%/wcl-raid-coach/` and its `Cache/` directory.

The installed Skill directory contains only program files and documentation. Report Indexes, Complete Bundles, Profiles, tasks, Guide Snapshots, and rendered Report Documents go to the data directory; Raw Pages and resumable checkpoints go to the cache directory. Run `doctor` to read the effective `data_root` and `cache_root` from its JSON output.

```text
reports/<report-code>/
|-- latest.json
`-- revisions/<revision>/
    |-- report.json
    `-- fights/<fight-id>/
        |-- manifest.json
        `-- events.jsonl.gz
ability-names.zhCN.json
ability-names.zhCN.meta.json
content-names.zhCN.json
content-names.zhCN.meta.json
outputs/reports/
|-- <html-sha256>.html
`-- <html-sha256>.json
outputs/advice/
`-- <advice-id>.json
outputs/personal-workflows/
|-- <workflow-id>.json
`-- index.json
outputs/personal-deliveries/
|-- <delivery-id>.json
`-- <finalization-id>.json
```

Fight Bundles are immutable within a Report Revision. Re-exporting a report creates a new revision directory.

`latest.json` is only a pointer; reproducible consumers should use the revision recorded in each manifest. Raw Pages are compressed separately so interrupted downloads can resume and normalization can be audited.

## Data And Safety Boundaries

- Only a Fight Bundle with `complete: true` in its manifest is eligible for Personal Review, Benchmark, or Guide analysis; Mechanic Review uses the ephemeral exception below.
- A Complete Bundle must reach an explicit `nextPageTimestamp: null`, preserve event ordering, stay within one Report Revision, and pass file hash checks.
- A Complete Bundle validates both the compressed event file SHA-256 and the uncompressed Canonical Event JSONL content SHA-256. Ranking Cohorts and Encounter Benchmarks use canonical-JSON content IDs rather than HMACs derived from the WCL client secret.
- Every pagination request repeats the fight's fixed `startTime` and `endTime`; Bundles made with the old collection protocol are rejected and must be prepared again.
- Canonical Events retain known fields only. Unknown field names and counts are recorded in the manifest; unknown values remain in the Raw Page cache.
- Character names and servers are retained locally to identify team members. Data shown in a conversation may be processed by the configured model provider.
- Query output is evidence, not a conclusion. Without an independent source of encounter mechanics, do not label damage avoidable or infer responsibility.
- A Mechanic Evidence Set exists only in the current process. It creates no Report Index, Raw Page, Fight Bundle, manifest, or checkpoint. It must follow filtered-event pagination to `nextPageTimestamp: null`, keep the fixed Boss Attempt range, and verify the same Report Revision before and after collection.
- Mechanic Review uses the newest rules shipped with the installed package rather than replaying historical hotfix rules by report date. Updating rules requires updating the package; output records the ruleset version, sources, and `selection_policy: latest`.
- Personal Review workflows, Advice, Report Indexes, deliveries, and finalizations are content-addressed Artifacts written by this CLI. An Artifact already written but not referenced by the final report remains as an orphan after assembly, rendering, or finalization failure; it requires explicit human or dedicated cleanup based on references and retention policy and must not be automatically deleted or overwritten.
- Personal Review timing uses the local monotonic and wall clocks. Deterministic injected clocks in tests validate state and continuity only; they do not represent actual local wall-clock elapsed time or measure WCL network time. The formal report command requires `--workflow`.
- `coach mechanics --compact` trims only current stdout and does not alter the Mechanic Evidence Set. A Focused Evidence Window is ephemeral follow-up evidence for explicit participants and a short time range, not a Complete Bundle or Canonical Event collection.
- Per-mechanic trigger, success, and failure counts describe rule-defined event signals and are `null` when the log cannot establish an outcome. An anomaly means only that a verified event pattern matched; it does not assign player responsibility, performance, or wipe causality.
- Coaching Artifacts are supported only when this CLI generates and consumes them in the user's local data or work directory. Hashes provide content identity and corruption detection, not origin authentication; externally supplied Artifacts are unsupported. Complete Bundles, Ranking Cohorts, Personal Reviews, Encounter Benchmarks, and Guide Snapshots using the former HMAC schemas must be rebuilt.

## Dataset Management

```bash
python -m wcl_raid_coach dataset list
python -m wcl_raid_coach cache status
python -m wcl_raid_coach dataset remove <REPORT_CODE> --confirm
python -m wcl_raid_coach cache clear --confirm
```

Destructive operations require `--confirm`. Clearing the cache preserves canonical Fight Bundles but removes local copies of unknown field values and download checkpoints.

## Development And Documentation

Ability names are first downloaded from `https://wago.tools/db2/SpellName/csv?locale=zhCN`. The CLI records the client build, source filename, and SHA-256 from a response such as `SpellName.12.1.0.69587.csv`. Delete `ability-names.zhCN.json` and `ability-names.zhCN.meta.json` from the data directory to download them again on the next relevant command. A download failure returns a structured `dataset_error`.

The Encounter/NPC mapping uses the current map scope declared in the package and requires all Wago source tables to have the same client build. Delete `content-names.zhCN.json` and `content-names.zhCN.meta.json` to rebuild it on the next `coach resolve` or `coach guide` requiring names; inspect only uses valid local mappings. An incomplete download, mismatched build, or missing current map returns a structured `dataset_error`.

```bash
make check
```

Equivalent manual checks:

```bash
python -m unittest -v
python -m compileall -q wcl_raid_coach tests tools
git diff --check
```

## Releases

`main` uses Conventional Commits for automated releases: `fix` triggers a patch, `feat` a minor, and `!` or `BREAKING CHANGE` a major release; other commit types do not release by themselves. The workflow synchronizes `SKILL.md`, `pyproject.toml`, and `wcl_raid_coach/__init__.py`, creates the release commit and `vX.Y.Z` tag, builds the sole Agent Skill zip from that immutable tag, creates a GitHub Release, and publishes the same zip to the existing `wcl-report-data` SkillHub listing. The SkillHub publishing identity is fixed at `name/slug: wcl-report-data`; it is independent of the bundled Python module name `wcl_raid_coach`.

A repository maintainer must configure a SkillHub personal API token as the GitHub Actions secret `SKILLHUB_TOKEN`. Typical Skill users do not need this token and still configure only `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET`. The release workflow pins and verifies the SkillHub CLI artifact and performs a local dry-run before publishing.

Documentation map:

- [Chinese README](README.md)
- [Domain vocabulary](CONTEXT.md)
- [Data contract](references/data-contract.en.md)
- [API notes](references/wcl-api.en.md)
- [Credentials and storage setup](references/setup.en.md)
- [Skill instructions](SKILL.md)
- [Original icon](assets/timewarp-inn-dog.svg)

The icon uses original golden-dog, inn, and time-portal shapes. It contains no Warcraft Logs, Blizzard, or in-game logos or character art.

This project is not affiliated with Warcraft Logs or Blizzard Entertainment. Follow the Warcraft Logs API terms and rate-limit requirements.
## Optional performance diagnostics

Place `--diagnostics` before the subcommand to emit numeric diagnostic JSON on stderr; the existing stdout JSON and domain-error contracts are preserved. For example:

```bash
python -m wcl_raid_coach --diagnostics inspect 'https://www.warcraftlogs.com/reports/REPORT_CODE'
```

Diagnostics count WCL/Wago attempts, retries, received response-body bytes and network duration by operation, plus mapping initialization, Complete Bundle validation, player analysis, report assembly/generation and lock waiting. They contain no credentials or event content and do not change Personal Review elapsed/`target_met` semantics. See [measurement boundaries](references/performance.en.md).
WCL requests coordinate quota and HTTP 429 cooldown across processes belonging to the same OS user. Changing workspace or data/cache roots does not bypass cooldown. Coordination state lives in `~/.wcl-report-data/api/` and contains no credentials; see [setup](references/setup.en.md).
