# Warcraft Logs API Notes

This document is the English companion to [the Chinese API notes](wcl-api.md). It records the API assumptions that affect collection and recovery.

## Authentication

- Token endpoint: `https://www.warcraftlogs.com/oauth/token`
- GraphQL endpoint: `https://www.warcraftlogs.com/api/v2/client`
- Accepted report hosts: `warcraftlogs.com`, `www.warcraftlogs.com`, and `cn.warcraftlogs.com`
- Grant: OAuth2 client credentials
- Canonical variables: `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET`
- Accepted aliases: `WCL_ID`, `WCL_SECRET`

CN report URLs are accepted as input and normalized to the global report URL. Authentication and GraphQL requests continue to use the official global endpoints.

Client credentials can read public and unlisted reports when the code is known. They cannot read private reports requiring user OAuth. Tokens are held in process memory only.

## Queries

Report indexing fetches the report revision, archive status, Retail game version, master actors and abilities, fight participation metadata, report difficulty metadata, ranking partition `id`, `name`, `compactName`, and `default`, and WCL zone encounter order. Strictly validated and normalized `zone.partitions` are persisted in the immutable Report Index for Personal Analysis comparison identity resolution. `zone.encounters` is returned only as current `inspect` selection metadata and is not persisted in existing immutable Report Indices.

General-guide resolution uses `worldData.zones` for the current unfrozen Retail raid zone, original encounter order, difficulties, and default partition. Exactly one current zone, one Heroic difficulty, and one default partition must exist; otherwise resolution stops rather than guessing.

Ranking candidates use the official `Encounter.characterRankings` query with exact encounter, difficulty, partition, class, and specialization, plus `externalBuffs: Exclude`. Ranking JSON remains untrusted input. WCL rankings normally omit source ID; the CLI must uniquely resolve it from the candidate report's actor/fight metadata before the candidate can enter the content-addressed recent Ranking Cohort.

Fight difficulty IDs are interpreted only through the `zone.difficulties { id name }` values returned for that report. They are not mapped through a hardcoded global enum because IDs can differ between WCL contexts.

WCL `translate: true` normalizes Report master ability names to English and does not accept a target locale. Current zhCN display names come from a complete local mapping downloaded from Wago Tools on first use with client-build provenance. WCL GraphQL `gameData.ability` has no locale argument and returns English names only.

Fight collection uses `Report.events` with:

- one `fightID`
- the fight's fixed `startTime` and `endTime` on every page
- `dataType: All`
- `includeResources: true`
- actor and ability IDs
- page limit 10,000

WCL may return more than the requested limit when multiple events share a pagination boundary. Every pagination request must repeat the fight `endTime`; omitting it can make a later page return empty.

The collector follows `nextPageTimestamp`, preserves event order, allows duplicate timestamps, and rejects repeated cursors.

Mechanic Review uses a separate `Report.events` query with one numeric `fightID`, the Boss Attempt start as the first-page `startTime`, the current cursor as each later `startTime`, a fixed Boss Attempt `endTime`, `dataType: All`, actor and ability IDs, a 10,000 event page limit, and a server-side `filterExpression` built from ruleset ability IDs plus `death`, `interrupt`, and `dispel`. It does not request `includeResources`. Returned events must lie between the current page cursor and the fixed end time, and pagination must reach `nextPageTimestamp: null`.

A Focused Evidence Window uses a separate `Report.events` query over a short range around an explicit fight-relative anchor. It issues a WCL `targetID` request for each selected Boss Attempt participant, then locally filters returned report actor target IDs and the damage, healing, absorb, aura, death, and resurrection event-type allowlist. It does not request `includeResources`; every participant query must reach `nextPageTimestamp: null`, followed by one Report Revision recheck after all queries complete.

## Rate Limits

The client retries transient connection failures and HTTP 500, 502, 503, and 504 responses with exponential backoff. HTTP 429 opens a process-local circuit breaker immediately.

Before WCL data queries, the client preserves at least 15 percent or 50 API points, whichever is larger. Report indexing reserves 500 points because its cost scales with report metadata.

Event and revision requests reserve the full retry budget and refresh the rate snapshot in the same GraphQL response. Persistent collection retains Raw Pages and checkpoints after a safe-reserve stop. Mechanic Review writes nothing and must restart.

The WCL client secret is used only for OAuth and does not establish local Artifact identity. Ranking Cohorts and Encounter Benchmarks use SHA-256 content IDs over canonical JSON; Complete Bundles hash the Report Index, Raw Pages, compressed event file, and Canonical Event content. These Artifacts are supported only for local generation and consumption; hashes do not authenticate origin.

## Revisions And Archives

The Report Revision is checked after the final event page. A changed revision prevents both Fight Bundle publication and a Mechanic Review result. A later persistent collection creates or uses the new revision directory; Mechanic Review recollects its ephemeral evidence.

Archived metadata may remain visible while events are inaccessible. A Fight Bundle or Mechanic Review is allowed only when WCL reports archived events as accessible to the current API client.
