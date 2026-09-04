# Repository Instructions

These rules apply to code, documentation, SkillHub packaging, and release work in this repository.

## Context

- Use the domain language in `CONTEXT.md`. In particular, distinguish a WCL Report, Report Revision, Report Index, Boss Attempt, Fight Bundle, Canonical Event, Raw Page, and Complete Bundle.
- Do not replace domain terms with casual synonyms such as "version", "pull", or "raw event" when describing persisted data or public behavior.
- Read `references/data-contract.md` before changing dataset identity, pagination, normalization, manifests, querying, or completeness rules. Keep `references/data-contract.en.md` synchronized when the contract changes.
- Read `references/wcl-api.md` before changing WCL requests, retries, rate limits, archives, or event collection. Keep `references/wcl-api.en.md` synchronized when the API behavior changes.
- Keep user-facing behavior documented in both `README.md` and `README.en.md`. Keep credential and storage guidance synchronized in `references/setup.md` and `references/setup.en.md`.

## Engineering

- Support Python 3.11 and newer using the standard library only. Keep `pyproject.toml` free of runtime dependencies unless the project requirements explicitly change.
- Preserve the CLI's JSON stdout and existing domain-error contract. Convert malformed API, checkpoint, Raw Page, manifest, and credential inputs into existing domain errors rather than leaking implementation exceptions.
- Preserve Report Revision isolation. A Complete Bundle must end at an explicit `nextPageTimestamp: null`, remain within the Boss Attempt range, pass hash checks, and match one Report Revision.
- Coordinate filesystem mutations through the existing report and cache locks. POSIX may prepare different reports concurrently; Windows intentionally serializes prepares because CRT byte-range locks are exclusive.
- Do not log, print, persist, or request client secrets or access tokens. Do not overwrite an existing credential file. Preserve the existing `.gitignore` protection for `.env` files.
- Keep generated data, caches, `__pycache__`, and build artifacts out of source changes. Do not modify unrelated user changes in a dirty worktree.

## Documentation And Assets

- Prefer concise, task-oriented examples that match the current CLI. If a path, flag, output field, or default changes, update the Chinese and English documentation together.
- Use ASCII for new source and documentation unless the existing language requires otherwise. Keep markdown links relative and verify that renamed files have no stale references.
- Original branding assets belong under `assets/`. Avoid Warcraft Logs, Blizzard, or in-game copyrighted logos and character art; use original shapes and clearly label original artwork when needed.
- `README.md`, `README.en.md`, `SKILL.md`, `references/`, `wcl_raid_coach/`, and `assets/` are the platform-neutral Agent Skill release inputs. Repository instructions, tests, build metadata, workflows, and repository tooling are not part of the SkillHub archive.

## Verification

- Bug fixes require a failing regression test before the implementation change when practical.
- Run `make check` before handoff. The completion criterion is a passing unit suite, passing `compileall`, and a clean `git diff --check`.
- For documentation-only changes, also check links and command snippets against the current CLI. For SVG assets, parse the file as XML and confirm the package archive contains the intended asset.
- A real WCL integration check is optional and must use existing local credentials without printing or persisting secrets.

## Releases

- Keep the version synchronized in `SKILL.md`, `pyproject.toml`, and `wcl_raid_coach/__init__.py`.
- Releases are automated from `main` using Conventional Commits: `fix` increments patch, `feat` increments minor, and `!` or `BREAKING CHANGE` increments major. Other commit types do not trigger a release.
- The release workflow synchronizes the three version files, commits and tags the release, then builds the artifact from that immutable tag with `make package REF=vX.Y.Z`.
- Run `make publish-dry-run REF=vX.Y.Z` before every SkillHub publish. Preserve `slug: wcl-raid-coach` so existing SkillHub installations update in place.
- `PACKAGE_PATHS` in `Makefile` is the release allowlist. Keep it synchronized with user-facing runtime documentation and assets.
- Package only allowlisted paths; keep repository instructions, tests, build metadata, and repository tooling outside the SkillHub zip.
