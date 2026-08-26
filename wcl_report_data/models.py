from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from .errors import InputError


RETAIL_HOSTS = {"warcraftlogs.com", "www.warcraftlogs.com", "cn.warcraftlogs.com"}


@dataclass(frozen=True)
class ReportRef:
    code: str
    fight: int | Literal["last"] | None = None
    source_hint: int | None = None

    @classmethod
    def parse(cls, value: str) -> "ReportRef":
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in RETAIL_HOSTS:
            raise InputError("Expected a Retail Warcraft Logs URL on warcraftlogs.com.")
        if parsed.username is not None or parsed.password is not None:
            raise InputError("WCL URLs must not contain user information.")

        parts = [part for part in parsed.path.split("/") if part]
        try:
            report_index = parts.index("reports")
            code = parts[report_index + 1]
        except (ValueError, IndexError) as exc:
            raise InputError("The URL does not contain /reports/<report-code>.") from exc
        if not code.isalnum():
            raise InputError("The report code contains unexpected characters.")

        params = parse_qs(parsed.query, keep_blank_values=True)
        params.update(parse_qs(parsed.fragment, keep_blank_values=True))
        return cls(
            code=code,
            fight=_fight_value(params.get("fight", [None])[0]),
            source_hint=_positive_int(params.get("source", [None])[0], "source"),
        )

    def canonical_url(self) -> str:
        fragment: list[str] = []
        if self.fight is not None:
            fragment.append(f"fight={self.fight}")
        if self.source_hint is not None:
            fragment.append(f"source={self.source_hint}")
        suffix = f"#{'&'.join(fragment)}" if fragment else ""
        return f"https://www.warcraftlogs.com/reports/{self.code}{suffix}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"canonical_url": self.canonical_url()}


def _fight_value(value: str | None) -> int | Literal["last"] | None:
    if value in {None, ""}:
        return None
    if value == "last":
        return "last"
    return _positive_int(value, "fight")


def _positive_int(value: str | None, field: str) -> int | None:
    if value in {None, ""}:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"The {field} parameter must be a positive integer, not {value!r}.") from exc
    if result <= 0:
        raise InputError(f"The {field} parameter must be positive.")
    return result
