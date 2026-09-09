# Performance diagnostics

[Chinese version](performance.md)

The global `--diagnostics` option enables process-local measurements for this CLI invocation and emits one JSON line with `kind: "wcl_diagnostics"` on stderr, including when execution raises a domain error. Measurement has not started on argument-parsing failure. It is disabled by default and creates no diagnostic file, background process or service. Stdout remains the command result.

- `network` aggregates each HTTP attempt under a fixed operation name, including OAuth, quota probes, GraphQL and Wago. `retries` counts attempts actually started after the first attempt. Monotonic `seconds` spans connection opening through response reading/closing, excluding backoff and JSON/gzip parsing. Received bytes are response-body bytes actually read by Python, counted before gzip decompression, including WCL HTTP error bodies and `IncompleteRead.partial`; headers, TLS and bytes not delivered to Python are excluded. Wago counts successfully read chunks; unread HTTP error bodies are excluded.
- `stages` records calls, inclusive `seconds`, and `exclusive_seconds` excluding measured child stages. Mapping initialization includes downloading, parsing and writing; player analysis includes Complete Bundle validation; report generation includes source revalidation and file writes. Network and stage durations can overlap and must not be added together. Lock waiting spans acquisition attempts through success or timeout, excluding execution while holding the lock.
- `counters.canonical_event_passes` counts started Canonical Event decompression/parsing traversals, including traversals aborted by corruption. It does not count Raw Page decompression or successful validations.
- `quota` retains the observation count and first/last valid numeric snapshots. Changes in `pointsSpentThisHour` can include consumption by other tools, OS users or machines, or quota-window resets. `attributable_cost` is always `null`; never label the difference as this command's established cost.

Diagnostics record only fixed labels and numbers, never URLs, report codes, players, query variables, response bodies, error text, secrets, tokens or authorization headers. Existing command results may contain their normal evidence fields; stderr diagnostics are separate.

Diagnostics do not write network measurements into Personal Review workflow/finalization artifacts or change elapsed, stage progress or final `target_met: null`. Agent synthesis remains separately unmeasured, and no end-to-end delivery guarantee is established.

From a repository checkout, run `python -m tools.benchmark --repetitions 3`. The tool uses synthetic HTTP responses and real local validation/rendering. See the [repository baseline record](https://github.com/Yarnus/wcl-report-data/blob/main/docs/performance-baseline.md) for inputs, cache state, environment, repetitions and results. `tools/`, `tests/` and `docs/` are excluded from the Skill archive.

Optional live WCL measurements use existing local credentials. Add `--diagnostics` to actual commands, record exact commands, input identities, cache state and repetitions, and calculate medians separately. First inspect and cold prepare require independent fresh data/cache roots; cached prepare requires priming complete evidence in the same roots. List measured scenarios and unrun checks explicitly; never call synthetic HTTP timings live network latency.
