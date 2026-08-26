# WorkBuddy Credentials And Storage

This document explains credential lookup and default storage locations. [Chinese version](workbuddy-setup.md)

WorkBuddy may run in a cloud sandbox with a persistent `/workspace`, or directly on local macOS, Linux, or Windows. Do not assume that `/workspace` exists.

## Credentials

Start with:

```bash
python -m wcl_report_data doctor
```

If the result contains `"wcl_api": "reachable"`, existing credentials are ready. `credential_source` identifies the source safely, for example `environment:WCL_ID`, but never prints a client secret or access token.

Process environment variables always take precedence. Without process credentials:

- With `--env-file`, only the explicitly supplied file is read.
- Without `--env-file`, the CLI checks `/workspace/.env` and then `.env` in the directory where the CLI was started.

Each variable pair must be complete and must not mix the canonical names with the alias names.

### Cloud WorkBuddy

Use `/workspace/.env` only when `/workspace` actually exists. An empty template may contain:

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

Never overwrite an existing file. Fill the template privately through a file editor or the platform's secret settings.

### Local Runs

When `/workspace` is absent, use the real workspace path and pass its environment file explicitly:

```bash
python -m wcl_report_data --env-file "<WORKSPACE>/.env" doctor
python -m wcl_report_data --env-file "<WORKSPACE>/.env" inspect "<WCL_URL>"
```

Do not ask the user to provide a client ID or secret in chat. Do not paste `.env` contents into chat, and do not commit `.env` to Git.

## Storage

When `/workspace` exists:

```text
/workspace/wcl-report-data/          prepared datasets
/workspace/.cache/wcl-report-data/   raw pages and resumable checkpoints
```

Local Unix/macOS defaults are:

```text
~/.local/share/wcl-report-data/      prepared datasets
~/.cache/wcl-report-data/            raw pages and resumable checkpoints
```

Windows uses `%LOCALAPPDATA%` for both locations, with the cache below `wcl-report-data/Cache`. All environments can override the paths with `WCL_REPORT_DATA_HOME` and `WCL_REPORT_DATA_CACHE`.

Clearing the cache preserves canonical Fight Bundles but deletes omitted unknown field values and download checkpoints.
