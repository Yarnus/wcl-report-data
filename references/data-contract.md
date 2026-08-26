# Dataset Contract

## Identity

A prepared dataset is identified by:

```text
(report_code, report_revision, schema_version)
```

A Fight Bundle adds one numeric `fight_id`. Files from different report revisions must never be combined. `latest.json` is only a pointer; reproducible consumers use the revision recorded in each manifest.

## Report Index

`report.json` contains:

- report metadata and archive accessibility
- report actors and abilities
- every WCL fight classified as `boss` or `trash`
- team participants with actor ID, name, server, class, specialization, and item level
- `packable` and `unpackable_reason`

Input-specific fight selection and source hints are returned by `inspect` rather than persisted in the immutable index. The source hint never filters actors or events.

## Fight Bundle

`manifest.json` is written last. Its presence with `complete: true` means:

1. every WCL event page reached `nextPageTimestamp: null`
2. pagination did not repeat a cursor
3. event timestamps remained ordered
4. the report revision was unchanged after collection
5. `events.jsonl.gz` was closed and hashed

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

Actor and ability names live in `report.json`; IDs are the event identity. Localized names are display data and must not be used as keys.

Known `fields` cover amounts, mitigation, healing, resources, health, aura stacks, casts, encounter metadata, combatant gear and talents, and observed combat statistics. WCL event JSON is not frozen. New keys are counted under `unknown_fields` but their values remain only in raw-page cache until the schema explicitly adopts them.

## Query Contract

`query` streams the gzip file and returns at most `limit` rows. `matched` counts all matching rows after the input cursor. When `truncated` is true, `next_cursor` is the final returned sequence and can be passed to the next call.

Time filters use `fight_time_ms`. Their bounds are inclusive.
