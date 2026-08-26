from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .errors import CredentialError


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str = field(repr=False)
    source: str


def resolve_credentials(
    *,
    environ: Mapping[str, str] | None = None,
    env_files: Sequence[Path] | None = None,
) -> Credentials:
    values = dict(os.environ if environ is None else environ)
    credentials = _credentials_from(values, "environment")
    if credentials is not None:
        return credentials

    candidates = list(env_files) if env_files is not None else _default_env_files()
    for path in _unique_paths(candidates):
        file_values = _read_env_file(path)
        credentials = _credentials_from(file_values, str(path))
        if credentials is not None:
            return credentials
    raise CredentialError(
        "Set WCL_CLIENT_ID and WCL_CLIENT_SECRET in the process environment or /workspace/.env."
    )


def default_data_root(
    *, environ: Mapping[str, str] | None = None, workspace: Path = Path("/workspace")
) -> Path:
    values = os.environ if environ is None else environ
    override = values.get("WCL_REPORT_DATA_HOME")
    if override:
        return Path(override).expanduser()
    if workspace.is_dir():
        return workspace / "wcl-report-data"
    if os.name == "nt" and values.get("LOCALAPPDATA"):
        return Path(values["LOCALAPPDATA"]) / "wcl-report-data"
    base = Path(values["XDG_DATA_HOME"]).expanduser() if values.get("XDG_DATA_HOME") else Path.home() / ".local" / "share"
    return base / "wcl-report-data"


def default_cache_root(
    *, environ: Mapping[str, str] | None = None, workspace: Path = Path("/workspace")
) -> Path:
    values = os.environ if environ is None else environ
    override = values.get("WCL_REPORT_DATA_CACHE")
    if override:
        return Path(override).expanduser()
    if workspace.is_dir():
        return workspace / ".cache" / "wcl-report-data"
    if os.name == "nt" and values.get("LOCALAPPDATA"):
        return Path(values["LOCALAPPDATA"]) / "wcl-report-data" / "Cache"
    base = Path(values["XDG_CACHE_HOME"]).expanduser() if values.get("XDG_CACHE_HOME") else Path.home() / ".cache"
    return base / "wcl-report-data"


def _default_env_files() -> list[Path]:
    return [Path("/workspace/.env"), Path.cwd() / ".env"]


def _unique_paths(paths: Sequence[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (FileNotFoundError, OSError):
        return {}
    result: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key in {"WCL_CLIENT_ID", "WCL_CLIENT_SECRET", "WCL_ID", "WCL_SECRET"}:
            result[key] = value
    return result


def _credentials_from(values: Mapping[str, str], source: str) -> Credentials | None:
    for client_key, secret_key in (
        ("WCL_CLIENT_ID", "WCL_CLIENT_SECRET"),
        ("WCL_ID", "WCL_SECRET"),
    ):
        client_id = values.get(client_key, "").strip()
        client_secret = values.get(secret_key, "").strip()
        if client_id and client_secret:
            label = f"{source}:{client_key}" if source == "environment" else source
            return Credentials(client_id, client_secret, label)
        if client_id or client_secret:
            raise CredentialError(f"{client_key} and {secret_key} must be configured as a complete pair.")
    return None
