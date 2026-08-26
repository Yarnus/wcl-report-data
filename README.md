# wcl-report-data

`wcl-report-data` is a WorkBuddy Agent Skill and Python 3.11 package that turns Retail Warcraft Logs raid reports into revisioned, team-level datasets. It uses the official WCL OAuth and GraphQL APIs and does not scrape report pages.

The first release prepares evidence only. It does not decide whether damage was avoidable, assign responsibility for deaths, compare rankings, or generate coaching conclusions.

## Requirements

- WorkBuddy web or Python 3.11+
- Internet access to `warcraftlogs.com`
- A Warcraft Logs API v2 client ID and client secret

The runtime has no third-party Python dependencies.

## WorkBuddy Setup

Create `/workspace/.env` without posting its contents in chat:

```dotenv
WCL_CLIENT_ID=your-client-id
WCL_CLIENT_SECRET=your-client-secret
```

The CLI also accepts the existing `WCL_ID` and `WCL_SECRET` names as a complete pair. Process environment variables take priority over `.env`. Credentials and access tokens are never written to datasets, cache, or command output.

Run:

```bash
python -m wcl_report_data doctor
```

WorkBuddy stores prepared datasets under `/workspace/wcl-report-data/` and resumable raw pages under `/workspace/.cache/wcl-report-data/`. Set `WCL_REPORT_DATA_HOME` or `WCL_REPORT_DATA_CACHE` to override either path.

## Basic Flow

Index a report:

```bash
python -m wcl_report_data inspect "https://www.warcraftlogs.com/reports/<code>"
```

Prepare a fight already selected in the URL:

```bash
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>#fight=12"
```

Prepare selected fights or all completed attempts for an encounter:

```bash
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>" --fight 12 --fight 15
python -m wcl_report_data prepare "https://www.warcraftlogs.com/reports/<code>" --encounter 3129
```

Query a complete bundle without loading the entire event stream into model context:

```bash
python -m wcl_report_data query "/workspace/wcl-report-data/reports/<code>/revisions/<revision>/fights/12/manifest.json" \
  --type damage --target-id 17 --limit 200
```

See `python -m wcl_report_data --help` and `SKILL.md` for the full workflow.

## Dataset Layout

```text
reports/<report-code>/
├── latest.json
└── revisions/<revision>/
    ├── report.json
    └── fights/<fight-id>/
        ├── manifest.json
        └── events.jsonl.gz
```

Fight Bundles are immutable within a report revision. Re-exported reports create a new revision directory. Raw WCL pages are compressed separately so interrupted downloads can resume and known-field normalization can be audited.

The canonical stream intentionally omits unknown event values. `manifest.json` lists every omitted field name and occurrence count. Clearing raw cache removes the only local copy of those omitted values.

## Privacy

Prepared report indexes retain character names and servers because later team review must identify participants. Data remains in the WorkBuddy workspace, but any event content displayed in chat may be processed by the configured model provider.

## Development

```bash
python -m unittest -v
python -m compileall -q wcl_report_data tests
```

Live checks use credentials from the same environment:

```bash
python -m wcl_report_data doctor
python -m wcl_report_data inspect "<PUBLIC_WCL_URL>"
```

This project is not affiliated with Warcraft Logs or Blizzard Entertainment. Respect Warcraft Logs API access rules and rate limits.
