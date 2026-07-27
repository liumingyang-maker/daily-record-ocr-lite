"""Preserve handwritten date text while deriving a safe machine sort value."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

RECORD_DATE = re.compile(
    r"^(?P<year>\d{2}|\d{4})(?P<separator>[./-])"
    r"(?P<month>\d{1,2})(?P=separator)(?P<day>\d{1,2})$"
)


@dataclass(frozen=True, slots=True)
class ParsedRecordDate:
    """A source date plus its non-destructive indexing metadata."""

    raw: str
    sort_value: str | None
    status: str


def parse_record_date(value: object) -> ParsedRecordDate:
    """Parse the supported handwritten formats without rewriting source text."""
    raw = str(value or "")
    candidate = raw.strip()
    if not candidate:
        return ParsedRecordDate(raw=raw, sort_value=None, status="UNKNOWN")

    match = RECORD_DATE.fullmatch(candidate)
    if match is None:
        return ParsedRecordDate(raw=raw, sort_value=None, status="UNPARSED")

    year_text = match.group("year")
    year = int(year_text) + 2000 if len(year_text) == 2 else int(year_text)
    try:
        parsed = date(year, int(match.group("month")), int(match.group("day")))
    except ValueError:
        return ParsedRecordDate(raw=raw, sort_value=None, status="UNPARSED")
    return ParsedRecordDate(raw=raw, sort_value=parsed.isoformat(), status="KNOWN")
