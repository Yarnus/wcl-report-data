# WCL Raid Coach

This context describes reproducible Retail raid evidence, live mechanic reviews, personal reviews, and ranked Boss guides.

## Evidence

**WCL Report**:
A Warcraft Logs upload identified by a report code and containing actors, abilities, and combat records.
_Avoid_: Log, connection

**Report Revision**:
A numbered edition of a WCL Report produced when the report is re-exported. Facts from different revisions never belong to the same evidence set.
_Avoid_: Version, latest report

**Report Index**:
The catalog of a WCL Report's participants and combat records at one Report Revision.
_Avoid_: Report summary, analysis

**Boss Attempt**:
A completed Retail raid fight against a recognized encounter, whether it ended in a kill or a wipe.
_Avoid_: Pull, run

**Encounter Designator**:
A difficulty code (`PT`, `H`, or `M`) followed by the one-based position of an encounter in WCL's raid-zone ordering, such as `H7`. It identifies a difficulty and encounter, never one Boss Attempt.
_Avoid_: Fight ID, Boss Attempt code

**Fight Bundle**:
The prepared team-level facts for one Boss Attempt at one Report Revision.
_Avoid_: Player analysis, fight report

**Canonical Event**:
A WCL combat event expressed in the evidence layer's stable vocabulary of known fields.
_Avoid_: Raw event, conclusion

**Raw Page**:
One unmodified page returned by WCL while collecting a Boss Attempt.
_Avoid_: Canonical Event

**Complete Bundle**:
A Fight Bundle whose complete WCL event range was collected without crossing a Report Revision boundary.
_Avoid_: Partial Bundle, cached fight

**Mechanic Evidence Set**:
The in-memory WCL metadata and complete filtered event range used to evaluate one Boss Attempt at one Report Revision against one Mechanic Ruleset. It is neither a Fight Bundle nor a Canonical Event collection.
_Avoid_: Complete Bundle, Raw Page, saved dataset

## Coaching

**Mechanic Review**:
A reconstruction of observable encounter outcomes for one Boss Attempt. An anomaly means that a verified event pattern matched; it does not assign responsibility or wipe causality.
_Avoid_: Personal Review, blame report

**Mechanic Ruleset**:
A versioned catalog of encounter- and difficulty-specific event signals, display names, validation status, expectations, and sources. Mechanic Review uses the newest rules shipped with the installed package, not rules selected by report date.
_Avoid_: Encounter Profile, generic rule DSL

**Coach Request**:
A normalized user goal for report data, a Personal Review, or a Raid Guide.
_Avoid_: Prompt, command

**Personal Review**:
An evaluation of one player in one Boss Attempt against a comparable Encounter Benchmark.
_Avoid_: Raid Guide, player history

**Raid Guide**:
Current-Retail encounter guidance for one specialization, supported by one or more Encounter Benchmarks and current sources.
_Avoid_: Personal Review, generic class guide

**Ranking Candidate**:
A ranked performance discovered through WCL that has not yet passed evidence and encounter eligibility checks.
_Avoid_: Reference Sample, top log

**Reference Sample**:
A Ranking Candidate that has a Complete Bundle and passes the cohort's hard conditions and Encounter Profile rules.
_Avoid_: Ranking Candidate

**Ranking Cohort**:
The content-addressed local record of Ranking Candidates and accepted Reference Samples for one encounter, difficulty, specialization, and ranking partition.
_Avoid_: Benchmark, leaderboard

**Encounter Benchmark**:
An aggregate of comparable Reference Samples for exactly one encounter, difficulty, specialization, and ranking partition.
_Avoid_: Ranking Cohort, multi-Boss average

**Specialization Profile**:
A validated, sourced declaration of current specialization abilities, resources, cooldown relationships, and role guardrails.
_Avoid_: Rotation code, simulation

**Encounter Profile**:
A validated, sourced declaration of encounter phases, mechanic anchors, priority targets, and sample eligibility rules.
_Avoid_: Boss guide, inferred mechanics

**Guide Snapshot**:
An immutable Raid Guide result bound to exact Profiles, Encounter Benchmarks, and source evidence.
_Avoid_: Latest guide, mutable report
