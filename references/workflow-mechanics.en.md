# Mechanics and priority review

[中文](workflow-mechanics.md). Enter from the matching [Skill route](../SKILL.md), preserving its selection, credential and evidence gates.

Rules cover the eight raid encounters in The Venomous Abyss (zone 53): Nek'zali, Entombed Sentinels, Vashnik, The Lost Explorers, Sszorak, The Twin Fangs, The Coiled Altar and Ula'tek, Normal/Heroic/Mythic. Exclude world boss Nymrissa Wavecaller (3379). Use the newest bundled rules, not historical rules inferred from report dates. Unverified difficulties produce observations only.

## Selection and execution

List choices for a bare report or Encounter Designator and wait for a numeric fight:

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_REPORT_URL>" --encounter H2
```

For mechanic facts use compact; for priority review use triage directly:

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_URL_WITH_NUMERIC_FIGHT>" --compact
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach triage "<WCL_URL_WITH_NUMERIC_FIGHT>"
```

Triage reuses one client and report metadata, completing mechanic pagination, revision checks, selection and necessary windows. Check revision before and after each window. Any failure rejects the combined result. No Report Index, Raw Page, Fight Bundle, manifest, checkpoint, persistent event cache or HTML is created.

Only verified/enabled/target complete player_anomaly_summary counts qualify. Aggregate record_count then event_count descending, actor_id ascending; at most three players. Use displayed compact anomaly times in ascending order, at most three distinct times per player. Only players in the same anomaly can share a window. Team scope remains tied and never ranks individuals. Compact displays at most 20 player anomalies per mechanic while summaries retain complete counts; disclose suppressed records and window truncation from coverage.

Death anomalies use their time. Otherwise inspect the anomaly window first; if an observed death's preceding ten seconds extend beyond the window, collect one supplemental window for that player. Default radius is ten seconds, clipped to the Boss Attempt. Status no_supported_candidate means the rules support no candidate, not that execution was correct. Do not request focused events or choose arbitrary players in this case.

## Additional focused questions

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach evidence "<WCL_URL_WITH_NUMERIC_FIGHT>" --at-ms <TIME_MS> --player-id <ACTOR_ID> --expected-identity <EVIDENCE_IDENTITY>
```

Copy the compact evidence_identity token exactly; it binds report/revision/fight. A mismatch requires a new mechanic review. Optional window-ms is at most 30000; repeated player-id accepts at most three explicit participants sharing the anchor. Each player is independently paginated, requested with targetID and filtered locally. Facts cover only allowed events received by those targets. Output is capped at 200 events, deaths/resurrections first, then nearest anchor, displayed chronologically; use returned actors/abilities for ID interpretation. Disclose truncation. No resources or persistence.

Answer with identity and kill/wipe, verified mechanic hits/times, chronological window facts, observed simultaneous team facts, then unestablished causality. Say priority candidate, tied, or no supported candidate. Team impact must already be observed by Mechanic Review, otherwise unestablished. Prepare only when full Personal Review, Benchmark or whole-attempt Canonical Events are required.

## Formal report

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach mechanics "<WCL_URL_WITH_NUMERIC_FIGHT>" --report --locale en
```

The collection process completes pagination and verifies revision before sanitizing/persisting the source, assembling and rendering. Save only identities, rules, counts, supported conclusions and flat minimal excerpts; never complete filtered events or arbitrary payloads. First-render failure removes the new source; identical content reuses immutable artifacts. Do not copy stdout into a source or bypass acquisition through generic render. Return a short summary and report.html_path, retaining source/document/report identity. Chinese uses locale zh-CN.
