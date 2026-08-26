# WorkBuddy Setup

WorkBuddy web provides Python 3.11 and a persistent `/workspace` directory.

## Credentials

Create `/workspace/.env` through the WorkBuddy file editor:

```dotenv
WCL_CLIENT_ID=your-client-id
WCL_CLIENT_SECRET=your-client-secret
```

Keep the file private and exclude it from any Git repository. Enter secrets in the file editor or platform secret controls, not in chat. The Skill reads only the four recognized WCL credential keys and never returns their values.

Process environment variables override `.env`. Each credential naming pair must be complete; names from different pairs are not mixed.

## Verification

From the installed Skill directory, run:

```bash
python -m wcl_report_data doctor
```

Expected fields include:

```json
{
  "ok": true,
  "python": "3.11.1",
  "credential_source": "/workspace/.env",
  "wcl_api": "reachable"
}
```

The source identifies where credentials were found without exposing them.

## Storage

Defaults:

```text
/workspace/wcl-report-data/          prepared datasets
/workspace/.cache/wcl-report-data/   raw pages and resumable checkpoints
```

Both persist with the WorkBuddy workspace. Clearing cache preserves canonical Fight Bundles but removes omitted unknown-field values and download checkpoints.
