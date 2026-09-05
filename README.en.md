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

A formal Mechanic Review, Personal Review, or Raid Guide can be expressed as its corresponding structured Report Document defined by the [dataset contract](references/data-contract.en.md), then rendered as self-contained HTML. This command does not access WCL or require credentials:

```bash
python -m wcl_raid_coach coach render "<WORK_DIR>/report.document.json"
```

The CLI returns `html_path`, `html_sha256`, `index_path`, `document_id`, and both schema versions. HTML loads no remote fonts, styles, scripts, or images and supports the system theme plus manual Auto/light/dark selection. A caller submits only the structured fields allowed for that document type, never raw HTML. Mechanic Review accepts only flat minimal evidence excerpts; Personal Review accepts no mechanic attribution or recommendations; Raid Guide accepts no rotation, talent, gear, or prescriptive advice absent from its Snapshot.

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

`coach review`, `coach benchmark`, `coach guide`, and `coach compare` consume only local Artifacts. When required local name mappings already exist, they do not read WCL credentials merely to verify an Artifact. Commands that access the WCL API still require OAuth client credentials.

## Encounter Designators And Name Mappings

The Skill understands Encounter Designators such as `PT6`, `H6`, and `M6`. The prefixes mean Normal, Heroic, and Mythic; the number is the one-based position in WCL's original `zone.encounters` list. A designator identifies only a difficulty and encounter. When a report has multiple matching Boss Attempts, the Skill lists explicit fight IDs and waits for a choice instead of selecting a kill, the latest attempt, or every attempt.

On the first `inspect`, `prepare`, `query`, or Guide generation, the CLI downloads the current Retail zhCN `SpellName` CSV from Wago Tools and creates a complete `ability-names.zhCN.json` plus metadata in the data directory. A valid existing JSON is reused without network access. A mapping may be used only when the ID also occurs in the Report Index `abilities[].gameID`. Guide and Skill user-facing text must use the mapped Chinese SpellName and must not translate names ad hoc; final guide generation stops when a mechanic Spell ID has no Chinese mapping. Chinese names are current-client display enrichment and do not modify the Report Index. Mechanic Review does not initialize this local mapping; it uses the Chinese and English mechanic names shipped in the versioned Mechanic Ruleset.

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

The Encounter/NPC mapping uses the current map scope declared in the package and requires all Wago source tables to have the same client build. Delete `content-names.zhCN.json` and `content-names.zhCN.meta.json` to rebuild it on the next `inspect`, `coach resolve`, or `coach guide`. An incomplete download, mismatched build, or missing current map returns a structured `dataset_error`.

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
