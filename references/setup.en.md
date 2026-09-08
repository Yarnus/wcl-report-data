# Credentials And Storage

This document describes the platform-neutral credential lookup order and default storage locations. [Chinese version](setup.md)

A typical user only needs to provide these values through the Agent host's private environment configuration:

```dotenv
WCL_CLIENT_ID=
WCL_CLIENT_SECRET=
```

Do not paste credentials into chat or store them in the installed Skill directory.

## Credentials

Start in the Skill root:

```bash
python -m wcl_raid_coach doctor
```

If the result contains `"wcl_api": "reachable"`, credentials are ready. `credential_source` safely identifies the source, such as `environment:WCL_CLIENT_ID`, without printing a client secret or access token.

The CLI first reads a complete credential pair from the process environment. A credential file must be passed explicitly:

```bash
python -m wcl_raid_coach --env-file "<PRIVATE_PATH>/wcl.env" doctor
python -m wcl_raid_coach --env-file "<PRIVATE_PATH>/wcl.env" inspect "<WCL_URL>"
```

Place `--env-file` before the subcommand. The CLI does not automatically read `.env` from the current directory or `/workspace`.

Each variable pair must be complete and pairs cannot be mixed. The canonical names are `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET`; the CLI temporarily accepts the paired aliases `WCL_ID` and `WCL_SECRET`.

An Agent must never request, print, log, or persist a client secret or access token and must never overwrite an existing credential file. Credential files must not be committed to Git or included in a Skill artifact.

## Persistent Data And Cache

Typical users do not need to configure storage paths. The CLI chooses the persistent data directory in this order:

1. global `--data-root` option;
2. `WCL_RAID_COACH_HOME`;
3. an existing persistent `/workspace`;
4. the operating system user data directory.

It chooses the cache directory in this order:

1. global `--cache-root` option;
2. `WCL_RAID_COACH_CACHE`;
3. an existing persistent `/workspace`;
4. the operating system user cache directory.

`/workspace` is a compatibility fallback for cloud Agent sandboxes, not a test for any particular host. Defaults are:

```text
Persistent /workspace:
  /workspace/wcl-raid-coach/          Report Indexes, Complete Bundles, Profiles, tasks, Guide Snapshots, and rendered reports
  /workspace/.cache/wcl-raid-coach/   Raw Pages and resumable checkpoints

Local Unix/macOS:
  ~/.local/share/wcl-raid-coach/
  ~/.cache/wcl-raid-coach/

Windows:
  %LOCALAPPDATA%/wcl-raid-coach/
  %LOCALAPPDATA%/wcl-raid-coach/Cache/
```

The `doctor` JSON output reports the effective `data_root` and `cache_root`. Advanced users and hosts may set `WCL_RAID_COACH_HOME` and `WCL_RAID_COACH_CACHE`, but typical users only configure the WCL credentials.

The installed Skill directory contains only program files and documentation. Skill updates must not affect persistent data or cache directories. Rendered Report Documents live under `outputs/reports/`; structured Personal Review Advice under `outputs/advice/`; Personal Review acquisition workflows and their artifact index under `outputs/personal-workflows/`; and delivery plus finalization records under `outputs/personal-deliveries/`. The `index.json` files in these directories register local content-addressed artifacts; they do not replace the source artifacts. Canonical paths, indexes, and SHA-256 prevent accidental arbitrary-path use and detect corruption, but do not authenticate a producer or resist a local process that can edit both artifact and index.

If assembly, rendering, or finalization fails, an immutable Advice, delivery, or workflow artifact that was written but is not referenced by the final Report Document remains as an orphan. It must not be overwritten or automatically deleted because a concurrent report may already reference it. Reclamation requires an explicit human or future dedicated cleanup command based on references and retention policy; cache clearing must not remove these artifacts. Clearing the cache still preserves Complete Bundles, Report Indexes, and rendered reports while removing local copies of unknown field values and download checkpoints. The public CLI has no raw timing parameters; Personal Review timing uses the local monotonic and wall clocks, and the 180/30-second measurement is trustworthy only within a cooperative local workspace. Deterministic injected clocks in tests validate state only and do not represent actual local elapsed time; `wcl_network_measurement` is `not_measured`. A Mechanic Evidence Set exists only in the current process and is not written to either directory; a rendered report stores only its minimal evidence excerpts.
