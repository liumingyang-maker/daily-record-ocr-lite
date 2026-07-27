from __future__ import annotations

import pytest

from lite_app.fusion.date_recovery import (
    parse_date_candidate,
    recover_formula_date,
)
from lite_app.ocr.base import OCRPage, OCRToken


@pytest.mark.parametrize(
    ("raw", "sort_date"),
    [
        ("22/9/3", "2022-09-03"),
        ("22/9/19", "2022-09-19"),
        ("22/9/27", "2022-09-27"),
        ("22/12/12", "2022-12-12"),
        ("23/1/7", "2023-01-07"),
        ("24.7.10", "2024-07-10"),
        ("24.7.19", "2024-07-19"),
    ],
)
def test_parse_date_candidate_preserves_raw_text(raw: str, sort_date: str) -> None:
    parsed = parse_date_candidate(raw)

    assert parsed is not None
    assert parsed.raw == raw
    assert parsed.sort_date == sort_date


@pytest.mark.parametrize(
    "raw",
    [
        "22/2/30",
        "22/13/1",
        "22/9",
        "50",
        "22/9/3 and 22/9/4",
        "221/9119",
        "22/913",
    ],
)
def test_parse_date_candidate_rejects_invalid_or_ambiguous_text(raw: str) -> None:
    assert parse_date_candidate(raw) is None


def _token(token_id: str, text: str, bbox: list[int]) -> OCRToken:
    x1, y1, x2, y2 = bbox
    return OCRToken(
        id=token_id,
        text=text,
        confidence=0.94,
        polygon=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        bbox=bbox,
        center_x=(x1 + x2) / 2,
        center_y=(y1 + y2) / 2,
    )


def _page(*tokens: OCRToken) -> OCRPage:
    return OCRPage(
        image_index=1,
        width=1000,
        height=1000,
        tokens=list(tokens),
        average_confidence=0.94,
        provider="paddleocr_v6",
        model="PP-OCRv6_medium",
        elapsed_ms=1,
    )


def test_recover_formula_date_uses_only_requested_formula_region() -> None:
    page = _page(
        _token("p1_t001", "22/9/3 (kg)", [80, 160, 260, 200]),
        _token("p1_t002", "22/9/19 (kg)", [80, 660, 280, 700]),
    )
    regions = {
        "formula_001": [0.0, 0.0, 1.0, 0.5],
        "formula_002": [0.0, 0.5, 1.0, 1.0],
    }

    candidate = recover_formula_date(
        formula_id="formula_001",
        vlm_value="",
        page=page,
        formula_regions=regions,
    )

    assert candidate is not None
    assert candidate.value == "22/9/3"
    assert candidate.token_ids == ["p1_t001"]
    assert candidate.requires_review is True


def test_recover_formula_date_rejects_multiple_dates_in_one_region() -> None:
    page = _page(
        _token("p1_t001", "22/9/3", [80, 140, 220, 180]),
        _token("p1_t002", "22/9/4", [300, 140, 440, 180]),
    )

    candidate = recover_formula_date(
        formula_id="formula_001",
        vlm_value="",
        page=page,
        formula_regions={"formula_001": [0.0, 0.0, 1.0, 0.5]},
    )

    assert candidate is None


def test_recover_formula_date_does_not_override_vlm_value() -> None:
    page = _page(_token("p1_t001", "22/9/3", [80, 140, 220, 180]))

    candidate = recover_formula_date(
        formula_id="formula_001",
        vlm_value="24.7.19",
        page=page,
        formula_regions={"formula_001": [0.0, 0.0, 1.0, 0.5]},
    )

    assert candidate is None


def test_recover_formula_date_rejects_valid_date_below_date_band() -> None:
    page = _page(_token("p1_t001", "22/9/3", [80, 420, 220, 460]))

    candidate = recover_formula_date(
        formula_id="formula_001",
        vlm_value="",
        page=page,
        formula_regions={"formula_001": [0.0, 0.0, 1.0, 0.5]},
    )

    assert candidate is None
