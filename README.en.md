# wcl-report-data

<p align="center">
  <img src="assets/timewarp-inn-dog.svg" width="220" alt="Original fantasy icon of a golden dog guarding a timewarp inn">
</p>

`wcl-report-data` is a WorkBuddy Agent Skill and Python 3.11+ package for turning Retail Warcraft Logs raid reports into reproducible, team-level fact datasets stored by Report Revision.

It uses only the official Warcraft Logs OAuth and GraphQL APIs; it does not scrape report pages.

The first release prepares facts only. It does not classify avoidable damage, assign blame for deaths, compare rankings, or produce review conclusions.

[Chinese documentation](README.md)

## Scope

- Supports Retail raid reports; Classic and Mythic+ are out of scope.
- Supports public and unlisted reports; private reports requiring user OAuth are not supported.
- Accepts report URLs from `warcraftlogs.com`, `www.warcraftlogs.com`, and `cn.warcraftlogs.com`.
- CN report URLs are normalized to the global site; API requests still use the official global WCL endpoints.
- Runtime code uses only the Python standard library.

## Quick Start

Requirements: Python 3.11 or newer, network access to `warcraftlogs.com`, and a Warcraft Logs API v2 client ID and client secret.

Run the CLI from the repository root or an installed Skill directory:

```bash
python -m wcl_report_data doctor
```

After `wcl_api` reports `reachable`, create a report index:

```bash
python -m wcl_report_data inspect "https://www.warcraftlogs.com/reports/<code>"
```

Prepare the fight selected in the URL:

```bash
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>#fight=12"
```

You can also prepare explicit fights or all completed attempts for an encounter:

```bash
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>" --fight 12 --fight 15
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>" --encounter 3129
```

Use the returned manifest to query events without loading the entire event stream into a model context:

```bash
python -m wcl_report_data query \
  "/workspace/wcl-report-data/reports/<code>/revisions/<revision>/fights/12/manifest.json" \
  --type damage --target-id 17 --limit 200
```

The CLI always writes JSON to standard output, including structured domain errors. See `python -m wcl_report_data --help` for all arguments and [the Skill instructions](SKILL.md) for the complete workflow.

## Credentials

Process environment variables take precedence over `.env` files. The canonical names are:

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

The CLI also accepts the paired aliases `WCL_ID` and `WCL_SECRET`. When using an explicit file, put the global option before the subcommand:

```bash
python -m wcl_report_data --env-file "<WORKSPACE>/.env" doctor
python -m wcl_report_data --env-file "<WORKSPACE>/.env" inspect "<WCL_URL>"
```

Never ask a user to paste a secret into chat, never overwrite an existing `.env`, and never print a client secret or access token. See [the setup guide](references/workbuddy-setup.en.md) for lookup order and storage paths.

## Storage Layout

The default data directory is `/workspace/wcl-report-data/` when `/workspace` exists, `~/.local/share/wcl-report-data/` on local Unix/macOS, and `%LOCALAPPDATA%/wcl-report-data/` on Windows.

Override the data directory with `WCL_REPORT_DATA_HOME`.

Raw pages and resumable checkpoints default to `/workspace/.cache/wcl-report-data/` or `~/.cache/wcl-report-data/`; Windows uses `wcl-report-data/Cache` below `%LOCALAPPDATA%`. Override it with `WCL_REPORT_DATA_CACHE`.

```text
reports/<report-code>/
|-- latest.json
`-- revisions/<revision>/
    |-- report.json
    `-- fights/<fight-id>/
        |-- manifest.json
        `-- events.jsonl.gz
```

Fight Bundles are immutable within a Report Revision. Re-exporting a report creates a new revision directory.

`latest.json` is only a pointer; reproducible consumers should use the revision recorded in each manifest. Raw Pages are compressed separately so interrupted downloads can resume and normalization can be audited.

## Data And Safety Boundaries

- Only a Fight Bundle with `complete: true` in its manifest is eligible for downstream analysis.
- A Complete Bundle must reach an explicit `nextPageTimestamp: null`, preserve event ordering, stay within one Report Revision, and pass file hash checks.
- Every pagination request repeats the fight's fixed `startTime` and `endTime`; Bundles made with the old collection protocol are rejected and must be prepared again.
- Canonical Events retain known fields only. Unknown field names and counts are recorded in the manifest; unknown values remain in the Raw Page cache.
- Character names and servers are retained locally to identify team members. Data shown in a conversation may be processed by the configured model provider.
- Query output is evidence, not a conclusion. Without an independent source of encounter mechanics, do not label damage avoidable or infer responsibility.

## Dataset Management

```bash
python -m wcl_report_data dataset list
python -m wcl_report_data cache status
python -m wcl_report_data dataset remove <REPORT_CODE> --confirm
python -m wcl_report_data cache clear --confirm
```

Destructive operations require `--confirm`. Clearing the cache preserves canonical Fight Bundles but removes local copies of unknown field values and download checkpoints.

## Development And Documentation

```bash
make check
```

Equivalent manual checks:

```bash
python -m unittest -v
python -m compileall -q wcl_report_data tests
git diff --check
```

Documentation map:

- [Chinese README](README.md)
- [Domain vocabulary](CONTEXT.md)
- [Data contract](references/data-contract.en.md)
- [API notes](references/wcl-api.en.md)
- [WorkBuddy setup guide](references/workbuddy-setup.en.md)
- [Skill instructions](SKILL.md)
- [Original icon](assets/timewarp-inn-dog.svg)

The icon uses original golden-dog, inn, and time-portal shapes. It contains no Warcraft Logs, Blizzard, or in-game logos or character art.

This project is not affiliated with Warcraft Logs or Blizzard Entertainment. Follow the Warcraft Logs API terms and rate-limit requirements.
