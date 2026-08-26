---
name: wcl-report-data
description: Prepare structured team-level datasets from Retail Warcraft Logs raid report URLs. Use when a user provides a WCL report link, needs report or fight data downloaded, wants events organized for later review, or needs a machine-readable foundation for team death and damage analysis.
slug: wcl-report-data
displayName: WCL Report Data
version: 1.0.0
summary: Prepare revisioned team-level Retail Warcraft Logs datasets for WorkBuddy.
license: MIT
homepage: https://github.com/Yarnus/wcl-report-data
compatibility: Requires WorkBuddy or Python 3.11+, internet access, and user-provided Warcraft Logs API client credentials.
metadata:
  tags: [warcraft-logs, world-of-warcraft, raid, structured-data]
---

# WCL Report Data

Prepare official Warcraft Logs data as reproducible team-level facts. Return structured results and paths in Chinese. Treat later coaching, avoidable-damage classification, and responsibility claims as separate work.

Run commands from this Skill directory with `python -m wcl_report_data`. The CLI writes JSON to stdout.

## Workflow

### 1. Check The Runtime

Run before the first WCL request:

```bash
python -m wcl_report_data doctor
```

When credentials are unavailable, direct the user to [WorkBuddy setup](references/workbuddy-setup.md). The user places credentials in `/workspace/.env`; they never paste a client secret into chat. A successful check reports `wcl_api: reachable` without exposing credential values.

Completion criterion: Python is at least 3.11, both data roots are writable, and WCL authentication succeeds.

### 2. Index The Report

For every supplied report URL, run:

```bash
python -m wcl_report_data inspect "<WCL_URL>"
```

The index always covers the report team. A URL `source` parameter is an input hint and never filters participants or events.

- No `fight`: return `fight_choices` and wait for the user to select a fight, encounter, or all completed Boss attempts.
- Numeric `fight`: continue to Step 3 with that fight.
- `fight=last`: use the actual final fight in report order. If it is trash or in progress, return its `unpackable_reason` and wait for another selection.

Keep choices compact: fight ID, encounter, kill or wipe, duration, progress, participant count, and packability. Do not silently select a different fight.

Completion criterion: `report.json` exists at `index_path`, the report is Retail and public or unlisted, and every selectable fight has an explicit numeric ID.

### 3. Prepare Requested Fights

Prepare one fight from its URL:

```bash
python -m wcl_report_data prepare "<WCL_URL_WITH_NUMERIC_FIGHT>"
```

Prepare explicit fights from a bare report URL:

```bash
python -m wcl_report_data prepare "<WCL_URL>" --fight 12 --fight 15
```

Prepare all completed attempts for one encounter:

```bash
python -m wcl_report_data prepare "<WCL_URL>" --encounter 3129
```

Run `--all-boss-fights` only when the user explicitly asks for all completed Boss attempts. Report the number of indexed fights and current rate-limit snapshot before starting a large batch.

The collector resumes raw-page checkpoints after transient failures. Respect `wcl_rate_limit`; keep completed bundles and resume later. A bundle is usable only when its `manifest.json` says `complete: true`.

Completion criterion: every requested fight returns a `manifest_path`, and no trash, in-progress fight, partial paginator, or mixed report revision is presented as complete.

### 4. Query Without Flooding Context

Use the manifest path returned by `prepare`:

```bash
python -m wcl_report_data query "<MANIFEST_PATH>" --type damage --target-id 17
```

Available filters are `--type`, `--source-id`, `--target-id`, `--ability-id`, `--from-ms`, `--to-ms`, and `--cursor`. The default limit is 200. When `truncated` is true, continue from `next_cursor` or narrow the filters.

Query output is evidence, not interpretation. Do not label damage avoidable, infer fault, or call a death preventable without a separate encounter-specific knowledge source.

Completion criterion: every returned event traces to `raw_ref`, and no query response exceeds the requested limit.

## Data Management

Inspect prepared datasets and raw cache:

```bash
python -m wcl_report_data dataset list
python -m wcl_report_data cache status
```

Deletion is explicit:

```bash
python -m wcl_report_data dataset remove <REPORT_CODE> --confirm
python -m wcl_report_data cache clear --confirm
```

Read [the data contract](references/data-contract.md) when consuming files directly or building later analysis. Read [the WCL API notes](references/wcl-api.md) when responses change, pagination fails, or an archived report is inaccessible.

## Boundaries

- Retail raids only; Classic and Mythic+ are unsupported.
- Public and unlisted reports only; private reports require user OAuth and are unsupported.
- Official WCL OAuth and GraphQL endpoints only; no page scraping or browser automation.
- Completed Boss attempts only; report indexes may list trash and in-progress fights but cannot package them.
- The canonical event schema retains known fields. Unknown field names and counts are disclosed; unknown values remain only in raw-page cache.
- Player names and servers remain in the local dataset. No data is sent anywhere except the official WCL API request path.
- The Skill prepares data. It does not classify mechanics, rank players, or produce coaching conclusions.
