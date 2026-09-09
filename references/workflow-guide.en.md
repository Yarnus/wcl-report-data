# Current raid guides and reference acquisition

[中文](workflow-guide.md). Preserve all [entrypoint](../SKILL.md) gates. Personal Review reads this only for missing candidates/Profiles and retains its existing workflow and three-sample target. General guides follow confirmation and the per-Boss ten-sample target below.

## Resolve, confirm and reuse

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach resolve --spec "Unholy DeathKnight" --encounter H7 --encounter H8
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach confirm "<TASK_ID>"
```

Resolve uses official metadata for the unique current Retail zone, Heroic difficulty, original encounter ordering, default partition and normalized specialization. Show names/identities and obtain explicit confirmation before rankings or events. An Encounter Designator is not a fight ID. Keep H7/H8 Cohorts, Encounter Profiles, Benchmarks and sample counts independent.

Search local compatible, current Specialization Profiles first; share identical game-version/partition/class/spec identity and sources across Bosses. Each Boss has its own game-version/partition/encounter/difficulty Encounter Profile. Validate completed chapters with their original Cohort/Profile/Complete Bundle evidence; acquire only missing work and disclose blockers for incomplete chapters. Names or previous success do not establish reuse; rerun existing benchmark eligibility/content and guide checks. Three-to-nine samples is low confidence, ten normal; fewer than three cannot support stable aggregation.

## Profiles and candidates

Prioritize Blizzard/WCL official material, maintained class communities/specialization guides/simulation documentation, cross-checking Wowhead/Icy Veins. Before reading or refreshing external Profile sources, read and follow [guide retrieval and article validation](guide-retrieval.en.md): after WebFetch fails, try bounded local HTTP retrieval of the same URL before browsers or alternatives. Profiles store only URL, title, access time, excerpt and content hash; guidance requires actually read, version-relevant article text.

When constructing Profiles, read coaching artifact and Advice rules in the [data contract](data-contract.en.md). Encounter eligibility declares priority/excluded targets, using NPC gameIDs for nonempty lists. Missing/invalid Profiles allow candidate display but not stable Benchmark generation.

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach profile "<WORK_DIR>/profile.json"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach candidates --game-version <GAME_VERSION> --encounter-id <ENCOUNTER_ID> --difficulty-id <DIFFICULTY_ID> --partition-id <PARTITION_ID> --class-name DeathKnight --spec-name Unholy --output "<WORK_DIR>/cohort.json"
```

Defaults select complete-identity candidates from the last 14 days, ten per Boss. Missing source IDs are resolved uniquely by character/server/class/spec, rejecting ambiguity. One invocation reuses report/fight metadata while validating each identity separately. Keep the entire last queried page and consume stable identities.

Candidates with numeric fights use prepare directly; explicitly selected candidates within one report can use batch prepare without inspect. Validate encounter/difficulty/partition/class/spec from the returned Report Index and coach review, then enforce Encounter Profile deaths/priority/excluded-target eligibility. Only complete, eligible evidence becomes a Reference Sample. Anonymize prose as Sample N (rank/score), retaining public WCL links.

## Aggregate and deliver

Aggregate each Boss independently with the compatible shared Specialization Profile:

```bash
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach benchmark "<WORK_DIR>/analysis-1.json" "<WORK_DIR>/analysis-2.json" "<WORK_DIR>/analysis-3.json" --cohort "<WORK_DIR>/cohort.json" --encounter-profile "<WORK_DIR>/encounter-profile.json" --specialization-profile "<WORK_DIR>/specialization-profile.json" --output "<WORK_DIR>/benchmark.json"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach guide "<WORK_DIR>/h7-benchmark.json" "<WORK_DIR>/h8-benchmark.json" --spec-display-name "Unholy Death Knight"
cd "<SKILL_ROOT>" && python -m wcl_raid_coach coach guide-report "<GUIDE_SNAPSHOT_JSON_PATH>"
```

Guide-report derives directly from the one verified Snapshot, retaining each chapter's independent Benchmark/Profile/sample/metric/ability/anchor/source identities and validating content ID/Markdown hash. Do not copy fields through Agent messages or mix Bosses. Deliver summary/report.html_path and audit identity. Snapshot Markdown is currently Chinese only: disclose this before generating for an English request; never present it as an English artifact.

Distinguish log facts, current-source findings and confidence-qualified inferences. Do not add rotation, talents, gear, phase strategy, specific advice or achievable targets absent from the Snapshot. Other constructed Report Documents use coach render under the contract: no caller HTML/CSS/JS, sources identified by path/SHA-256.

Chinese Spell gates require specific ability_id links and verified full Wago zhCN SpellName/metadata. Do not reverse-match English names or translate ad hoc; missing mechanic Spell names stop final guide generation. Check anchors, statistics, first casts and referenced advice Spells. Unconfirmed Spell terms are mechanic descriptions. JSON may retain IDs/WCL names/builds for audit. Encounter/NPC names use separate content mappings; NPC localization is encounter-scoped display, never actor identity, with original names on misses. Mechanic Review's bundled rule names do not require this download.

On rate limits/interruption retain persisted checkpoints and completed chapters, using coach status/record for progress. Partial chapters disclose blockers without weakening evidence. Temporary mechanic evidence has no checkpoint.
