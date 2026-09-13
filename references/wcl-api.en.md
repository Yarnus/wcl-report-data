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

Explicit selections within one WCL Report should use one batch `prepare`, sharing one Report Index query; each Boss Attempt still checks its Report Revision after collection. The WclClient used by one candidate discovery reuses actor/fight metadata in memory by `(report_code, fight_id)`. Each candidate still independently matches character, server, class, and specialization, rejecting ambiguous identities. This cache is not persisted and does not establish Complete Bundle eligibility or Report Revision validity.

Report indexing fetches the report revision, archive status, Retail game version, master actors and abilities, fight participation metadata, report difficulty metadata, ranking partition `id`, `name`, `compactName`, and `default`, and WCL zone encounter order. Strictly validated and normalized `zone.partitions` are persisted in the immutable Report Index for Personal Analysis comparison identity resolution. `zone.encounters` is returned only as current `inspect` selection metadata and is not persisted in existing immutable Report Indices.

General-guide resolution uses `worldData.zones` for the current unfrozen Retail raid zone, original encounter order, difficulties, and default partition. Exactly one current zone, one Heroic difficulty, and one default partition must exist; otherwise resolution stops rather than guessing.

Ranking candidates use the official `Encounter.characterRankings` query with exact encounter, difficulty, partition, class, and specialization, plus `externalBuffs: Exclude`. Ranking JSON remains untrusted input. WCL rankings normally omit source ID; the CLI must uniquely resolve it from the candidate report's actor/fight metadata before the candidate can enter the content-addressed recent Ranking Cohort.

Personal Review ranking discovery and sample qualification are separate stages. A Ranking Candidate becomes a Reference Sample only after Complete Bundle, hard-condition, and Encounter Profile eligibility checks. Fresh acquisition targets 3 Reference Samples and replaces a rejection by its stable Cohort `report_code:fight_id:source_id`; Raid Guide and low-level `coach candidates` retain a default target of 10. A Ranking Cohort retains the complete deduplicated final queried page and records the actual queried page range, WCL `hasMorePages`, `target_reached`, local `truncated`, and derived `exhausted` state. Candidates after the target on that page can therefore replace rejections without another request. Page exhaustion is proven only when `hasMorePages` is not true and the result was not truncated. Budget closure, proven exhaustion, API failure, or the WCL 429 circuit breaker stops scheduling before the next optional operation but cannot cancel an in-flight request or discard Raw Pages and checkpoints.
The delivery finalization artifact records elapsed time from workflow selection through validation, locks, persistence, and HTML/index hash confirmation, plus `target_met` and `completion_status`. Timing continuity requires monotonic non-regression and a current wall-minus-monotonic baseline within the persisted baseline's recorded tolerance; otherwise progress is retained while optional acquisition and continuous timing stop. The session marker is persisted metadata for local diagnostics only, not a strict equality check.

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

A Focused Evidence Window uses a separate `Report.events` query over a short range around an explicit fight-relative anchor. It issues a WCL `targetID` request for each selected Boss Attempt participant, then locally filters returned report actor target IDs and the damage, healing, absorb, aura, death, and resurrection event-type allowlist. The caller must pass the previous stage's expected identity binding the WCL Report, Report Revision, and Boss Attempt; it must match before collection, every participant query must reach `nextPageTimestamp: null`, and the Report Revision must match again after all queries complete. The query does not request `includeResources`.

## Rate Limits

`coach triage` uses one WclClient, one full report metadata query, and its in-memory token. It checks Report Revision after Mechanic Review, before each Focused Evidence Window, and again after that window's pagination. Windows retain targetID filtering, fixed ranges, explicit null termination, and local participant filtering. API failure, shared cooldown, or a revision change rejects the combined result without persisting event evidence.

The client retries transient connection failures and HTTP 500, 502, 503, and 504 responses with exponential backoff. Every OAuth, quota probe, GraphQL and retry HTTP attempt passes the same OS user's file lock. HTTP 429 immediately opens the process-local circuit breaker and publishes shared cooldown, blocking new requests from other workspaces or data roots.

Before WCL data queries, the client preserves at least 15 percent or 50 API points, whichever is larger. Report indexing reserves 500 points because its cost scales with report metadata.

Event and revision requests reserve the full retry budget and refresh the rate snapshot in the same GraphQL response. Persistent collection retains Raw Pages and checkpoints after a safe-reserve stop. Mechanic Review writes nothing and must restart.

The shared gate additionally debits a conservative 500 points for each Report Index HTTP attempt or 10 for other GraphQL attempts; failures without a new quota observation retain the debit. OAuth has no assumed point cost. Valid shared snapshots satisfy quota initialization without duplicate probes; diagnostic quota observations count only actual API responses. Other clients can still consume quota, so this cannot guarantee zero server-side 429 responses.

Cooldown uses valid `Retry-After` seconds or HTTP date first, then reliable future quota reset information, otherwise 60 seconds. Active cooldown returns `wcl_rate_limit` immediately without sleeping through a quota window; errors provide shared cooldown or known reset Unix times. After expiry, probes run under the file lock; successful observations are reused by other processes and another 429 reinstates cooldown. Ordinary queries after stale observations or interrupted requests require a `doctor` refresh first. Corrupt state and clock-continuity anomalies return domain errors and never automatically restore a full budget.

The WCL client secret is used only for OAuth and does not establish local Artifact identity. Ranking Cohorts and Encounter Benchmarks use SHA-256 content IDs over canonical JSON; Complete Bundles hash the Report Index, Raw Pages, compressed event file, and Canonical Event content. These Artifacts are supported only for local generation and consumption; hashes do not authenticate origin or resist a local process that can edit both artifact and index. Personal Review's 180/30-second targets use monotonic and wall-clock measurements within a cooperative local workspace; `wcl_network_measurement` is `not_measured`, so this is not a WCL network benchmark.

## Revisions And Archives

The Report Revision is checked after the final event page. A changed revision prevents both Fight Bundle publication and a Mechanic Review result. A later persistent collection creates or uses the new revision directory; Mechanic Review recollects its ephemeral evidence.

Archived metadata may remain visible while events are inaccessible. A Fight Bundle or Mechanic Review is allowed only when WCL reports archived events as accessible to the current API client.

Run `coach personal-workflow-init` immediately after Boss Attempt/player selection and before target Complete Bundle retrieval, Ranking Candidate discovery, and Profile retrieval/synthesis. Initialization persists only selected report/fight/actor identity and the internal clock origin. Later `coach personal-workflow --previous-workflow` calls bind Analysis, Ranking Cohort, and Profiles to that identity; elapsed includes invocation gaps and therefore covers candidate, Profile, and Agent work. WCL network time remains `not_measured`; Agent synthesis cannot be timed separately, so finalization marks it `unavailable` and final `target_met` is `null`.
## Optional request diagnostics

The global `--diagnostics` option separately measures HTTP attempts, received body bytes and monotonic network duration for OAuth, quota probes, GraphQL and retries in this invocation. First/last valid quota snapshots are observations and cannot exclude consumption by other clients. This does not change workflow `wcl_network_measurement` or `target_met`; see [measurement boundaries](performance.en.md).
## Mixed-report metadata

A mixed report's principal zone may be a dungeon season. Only for a Retail report with a non-raid principal zone and non-Mythic+ Encounters, request `worldData.zones` (including difficulty `sizes`) to resolve exactly one raid zone by Encounter membership. This supplemental request uses existing shared scheduling and retries. Preserve the principal zone, never guess difficulty IDs, and never merge multiple raid zones.
