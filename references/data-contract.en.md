# Dataset Contract

This document is the English companion to [the Chinese data contract](data-contract.md). It defines the stable identity and completeness rules for prepared data.

## Identity

A prepared dataset is identified by:

```text
(report_code, report_revision, schema_version)
```

A Fight Bundle adds one numeric `fight_id`. Files from different Report Revisions must never be combined. `latest.json` is only a pointer; reproducible consumers use the revision recorded in each manifest.

## Report Index

`report.json` contains:

- report metadata and archive accessibility
- report actors and abilities
- every WCL fight classified as `boss` or `trash`
- team participants with actor ID, name, server, class, specialization, and item level
- `packable` and `unpackable_reason`

Fight selection and source hints from a particular input are returned by `inspect` rather than persisted in the immutable index. A source hint never filters actors or events.

`inspect` also returns one-based `encounter_choices` in the original WCL `zone.encounters` array order. This list is current-query selection metadata used to interpret Encounter Designators and is not persisted in existing Report Indices. Consumers must not sort it or filter out encounters absent from the report's fights.

Fight `difficulty` is the raw numeric ID returned by WCL. Resolve it against `report.zone.difficulties` from the same report. Do not use a static global mapping.

The compact `selected_fight` and `fight_choices` returned by `inspect` include the resolved `difficulty_name`. An unmatched ID produces `null`, not a guessed name.

## Fight Bundle

`manifest.json` is written last. Its presence with `complete: true` means that:

1. Every WCL event page reached `nextPageTimestamp: null`.
2. Pagination did not repeat a cursor.
3. Event timestamps remained ordered.
4. The Report Revision was unchanged after collection.
5. `events.jsonl.gz` was closed and hashed.

All pages use the same inclusive fight start and end timestamps. Bundles created by an older collection protocol are rejected and must be prepared again.

The manifest records event counts by type, raw-page hashes, the canonical stream hash, collection options, and unknown field counts.

## Canonical Events

Each gzip JSONL row has this envelope:

```json
{
  "sequence": 42,
  "report_time_ms": 123456,
  "fight_time_ms": 3456,
  "type": "damage",
  "source": {"actor_id": 100, "instance_id": 1},
  "target": {"actor_id": 17, "instance_id": null},
  "ability_id": 456789,
  "fields": {"amount": 1000, "absorbed": 200},
  "raw_ref": {"page": 1, "index": 42}
}
```

Actor and ability names live in `report.json`; IDs are event identity. Localized names are display data and must not be used as keys.

`ability-names.zhCN.json` is current-client display enrichment kept outside the Report Index. It may be applied only when a Canonical Event `ability_id` also matches Report Index `abilities[].gameID`. A hit still retains the WCL name, ability ID, and mapping build provenance; a miss uses the WCL name. Mapping updates do not alter Report Revision facts or Complete Bundle identity.

Known fields cover amounts, mitigation, healing, resources, health, aura stacks, casts, encounter metadata, combatant gear and talents, and observed combat statistics.

WCL event JSON is not frozen. New keys are counted under `unknown_fields`; their values remain only in the Raw Page cache until the schema explicitly adopts them.

## Query Contract

`query` streams the gzip file and returns at most `limit` rows. `matched` counts all matching rows after the input cursor. When `truncated` is true, `next_cursor` is the final returned sequence and can be passed to the next call.

Time filters use `fight_time_ms`, and their bounds are inclusive.
