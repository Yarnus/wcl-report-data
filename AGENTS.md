# Repository Instructions

## Context

- Use the domain language in `CONTEXT.md`. Read it when naming reports, revisions, Boss Attempts, Fight Bundles, Canonical Events, or Raw Pages.
- Read `references/data-contract.md` before changing dataset identity, pagination, normalization, manifests, querying, or completeness rules.
- Read `references/wcl-api.md` before changing WCL requests, retries, rate limits, or event collection.

## Engineering

- Support Python 3.11 and newer using the standard library only. Keep `pyproject.toml` free of runtime dependencies unless the project requirements explicitly change.
- Preserve Report Revision isolation. A Complete Bundle must end at an explicit `nextPageTimestamp: null`, remain within the Boss Attempt range, pass hash checks, and match one Report Revision.
- Coordinate filesystem mutations through the existing report and cache locks. POSIX may prepare different reports concurrently; Windows intentionally serializes prepares because CRT byte-range locks are exclusive.
- Convert malformed API, checkpoint, Raw Page, manifest, and credential inputs into the existing domain errors so the CLI can keep its JSON error contract.

## Verification

- Bug fixes require a failing regression test before the implementation change when practical.
- Run `make check` before handoff. The completion criterion is a passing unit suite, passing `compileall`, and a clean `git diff --check`.
- A real WCL integration check is optional and must use existing local credentials without printing or persisting secrets.

## Releases

- Keep the version synchronized in `SKILL.md`, `pyproject.toml`, and `wcl_report_data/__init__.py`.
- Commit and tag the release before packaging. Build the artifact from that immutable ref with `make package REF=vX.Y.Z`.
- Run `make publish-dry-run REF=vX.Y.Z` before `make publish REF=vX.Y.Z CHANGELOG="..."`.
- `PACKAGE_PATHS` in `Makefile` is the release allowlist. Package only those runtime files; keep repository instructions, tests, build metadata, and repository tooling outside the SkillHub zip.
