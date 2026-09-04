from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
COMMIT_PATTERN = re.compile(r"^(?P<type>[a-zA-Z][a-zA-Z0-9-]*)(?:\([^\n)]*\))?(?P<breaking>!)?: .+")
VERSION_FILES = {
    "SKILL.md": re.compile(r"(?m)^version: (?P<version>\d+\.\d+\.\d+)$"),
    "pyproject.toml": re.compile(r'(?m)^version = "(?P<version>\d+\.\d+\.\d+)"$'),
    "wcl_raid_coach/__init__.py": re.compile(
        r'(?m)^__version__ = "(?P<version>\d+\.\d+\.\d+)"$'
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan and apply wcl-raid-coach releases.")
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--base-ref", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("version")
    args = parser.parse_args()
    root = args.root.resolve()

    if args.command == "plan":
        print(json.dumps(release_plan(root, args.base_ref), ensure_ascii=False))
    else:
        apply_version(root, args.version)
    return 0


def release_plan(root: Path, base_ref: str) -> dict[str, object]:
    current = synchronized_version(root)
    records = _commit_records(root, base_ref)
    bump = _required_bump(records)
    next_version = _bump(current, bump) if bump else None
    subjects = [record[0] for record in records if _commit_bump(*record)]
    return {
        "release": bump is not None,
        "bump": bump,
        "current_version": current,
        "next_version": next_version,
        "tag": f"v{next_version}" if next_version else None,
        "changelog": "\n".join(f"- {subject}" for subject in subjects),
    }


def synchronized_version(root: Path) -> str:
    versions = {}
    for relative, pattern in VERSION_FILES.items():
        path = root / relative
        match = pattern.search(path.read_text(encoding="utf-8"))
        if match is None:
            raise SystemExit(f"Unable to find version in {relative}.")
        versions[relative] = match.group("version")
    if len(set(versions.values())) != 1:
        raise SystemExit(f"Version files are not synchronized: {versions}")
    return next(iter(versions.values()))


def apply_version(root: Path, version: str) -> None:
    if VERSION_PATTERN.fullmatch(version) is None:
        raise SystemExit(f"Invalid semantic version: {version}")
    synchronized_version(root)
    for relative, pattern in VERSION_FILES.items():
        path = root / relative
        text = path.read_text(encoding="utf-8")
        updated, count = pattern.subn(lambda match: match.group(0).replace(match.group("version"), version), text)
        if count != 1:
            raise SystemExit(f"Expected one version field in {relative}, found {count}.")
        path.write_text(updated, encoding="utf-8")


def _commit_records(root: Path, base_ref: str) -> list[tuple[str, str]]:
    separator = "\x1f"
    record_separator = "\x1e"
    completed = subprocess.run(
        ["git", "-C", str(root), "log", f"{base_ref}..HEAD", f"--format=%s{separator}%b{record_separator}"],
        check=True,
        capture_output=True,
        text=True,
    )
    records = []
    for raw in completed.stdout.split(record_separator):
        raw = raw.strip("\n")
        if not raw or separator not in raw:
            continue
        subject, body = raw.split(separator, 1)
        records.append((subject.strip(), body.strip()))
    return records


def _commit_bump(subject: str, body: str) -> str | None:
    match = COMMIT_PATTERN.match(subject)
    if match is None:
        return None
    if match.group("breaking") or "BREAKING CHANGE:" in body or "BREAKING-CHANGE:" in body:
        return "major"
    if match.group("type").lower() == "feat":
        return "minor"
    if match.group("type").lower() == "fix":
        return "patch"
    return None


def _required_bump(records: list[tuple[str, str]]) -> str | None:
    priority = {None: 0, "patch": 1, "minor": 2, "major": 3}
    result = None
    for record in records:
        candidate = _commit_bump(*record)
        if priority[candidate] > priority[result]:
            result = candidate
    return result


def _bump(version: str, kind: str) -> str:
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise SystemExit(f"Invalid semantic version: {version}")
    major, minor, patch = (int(part) for part in match.groups())
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


if __name__ == "__main__":
    raise SystemExit(main())
