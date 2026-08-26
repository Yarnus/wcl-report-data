# Warcraft Logs API Notes

## Authentication

- Token endpoint: `https://www.warcraftlogs.com/oauth/token`
- GraphQL endpoint: `https://www.warcraftlogs.com/api/v2/client`
- Accepted report hosts: `warcraftlogs.com`, `www.warcraftlogs.com`, and `cn.warcraftlogs.com`

CN report URLs are accepted as input and normalized to the global report URL. Authentication and GraphQL requests continue to use the global official endpoints.
- Grant: OAuth2 client credentials
- Canonical variables: `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET`
- Accepted aliases: `WCL_ID`, `WCL_SECRET`

Client credentials can read public reports and unlisted reports when the code is known. They cannot read private reports requiring user OAuth. Tokens are held in process memory only.

## Queries

Report indexing fetches report revision, archive status, Retail game version, master actors and abilities, and fight participation metadata.

Fight collection uses `Report.events` with:

- one `fightID`
- the fight's fixed `startTime` and `endTime` on every page
- `dataType: All`
- `includeResources: true`
- actor and ability IDs
- page limit 10,000

WCL may return more than the requested limit when multiple events share a pagination boundary. Every pagination request must repeat the fight `endTime`; omitting it can make a later page return empty. The collector uses `nextPageTimestamp`, preserves event order, allows duplicate timestamps, and rejects repeated cursors.

## Rate Limits

The client retries transient connection failures and HTTP 500, 502, 503, and 504 responses with exponential backoff. HTTP 429 opens a process-local circuit breaker immediately.

Before WCL data queries, the client preserves at least 15 percent or 50 API points, whichever is larger. Report indexing reserves 500 points because its cost scales with report metadata; event and revision requests reserve the full retry budget and refresh the rate snapshot in the same GraphQL response. Raw pages and checkpoints remain available after a safe-reserve stop so the next invocation can resume.

## Revisions And Archives

The report revision is checked after the final event page. A changed revision prevents Fight Bundle publication. The next invocation creates or uses the new revision directory.

Archived metadata may remain visible while events are inaccessible. A Fight Bundle is allowed only when WCL reports archived events as accessible to the current API client.
