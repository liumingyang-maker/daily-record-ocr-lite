"""Fail-closed recovery of formula-local handwritten dates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..date_values import parse_record_date
from ..ocr.base import OCRPage, OCRToken
from .association import AssociatedOCRCandidate

_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{2}|\d{4})\s*([./-])\s*(\d{1,2})\s*\2\s*(\d{1,2})(?!\d)"
)
_DATE_BAND_RATIO = 0.45


@dataclass(frozen=True, slots=True)
class ParsedDateCandidate:
    raw: str
    sort_date: str


def parse_date_candidate(text: str) -> ParsedDateCandidate | None:
    """Return one valid date without changing its original spelling."""
    matches = list(_DATE_PATTERN.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    raw = match.group(0)
    parsed = parse_record_date(raw)
    if parsed.status != "KNOWN" or parsed.sort_value is None:
        return None
    return ParsedDateCandidate(
        raw=raw,
        sort_date=parsed.sort_value,
    )


def recover_formula_date(
    *,
    formula_id: str,
    vlm_value: str,
    page: OCRPage,
    formula_regions: dict[str, list[float] | None],
) -> AssociatedOCRCandidate | None:
    """Recover one date from the upper date band of one formula region."""
    if vlm_value.strip():
        return None
    region = formula_regions.get(formula_id)
    if not _valid_region(region) or not page.width or not page.height:
        return None
    assert region is not None
    date_band_bottom = region[1] + (region[3] - region[1]) * _DATE_BAND_RATIO
    matched: list[tuple[ParsedDateCandidate, OCRToken]] = []
    for token in page.tokens:
        token_bbox = [
            token.bbox[0] / page.width,
            token.bbox[1] / page.height,
            token.bbox[2] / page.width,
            token.bbox[3] / page.height,
        ]
        if not (
            region[0] <= token_bbox[0]
            and region[1] <= token_bbox[1]
            and token_bbox[2] <= region[2]
            and token_bbox[3] <= date_band_bottom
        ):
            continue
        parsed = parse_date_candidate(token.text)
        if parsed is not None:
            matched.append((parsed, token))
    values = {parsed.raw for parsed, _ in matched}
    if len(values) != 1:
        return None
    value = next(iter(values))
    tokens = [token for parsed, token in matched if parsed.raw == value]
    return AssociatedOCRCandidate(
        value=value,
        token_ids=[token.id for token in tokens],
        bbox=_normalized_tokens_bbox(tokens, page),
        confidence=min(token.confidence for token in tokens),
        method="formula_local_date",
        association_score=0.75,
        reasons=["仅在当前配方日期区域发现唯一合法日期"],
        requires_review=True,
    )


def _valid_region(value: list[float] | None) -> bool:
    return bool(
        value
        and len(value) == 4
        and 0.0 <= value[0] < value[2] <= 1.0
        and 0.0 <= value[1] < value[3] <= 1.0
    )


def _normalized_tokens_bbox(
    tokens: list[OCRToken], page: OCRPage
) -> list[float]:
    return [
        min(token.bbox[0] for token in tokens) / page.width,
        min(token.bbox[1] for token in tokens) / page.height,
        max(token.bbox[2] for token in tokens) / page.width,
        max(token.bbox[3] for token in tokens) / page.height,
    ]
