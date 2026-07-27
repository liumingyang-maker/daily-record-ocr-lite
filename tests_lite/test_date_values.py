from __future__ import annotations

import pytest

from lite_app.date_values import parse_record_date


@pytest.mark.parametrize(
    ("raw", "sort_value"),
    [
        ("24.7.19", "2024-07-19"),
        ("22/9/27", "2022-09-27"),
        ("2024-7-9", "2024-07-09"),
        ("2024.07.09", "2024-07-09"),
        ("2024/07/09", "2024-07-09"),
        ("2024-07-09", "2024-07-09"),
    ],
)
def test_parse_record_date_preserves_raw_and_builds_iso_sort_value(raw, sort_value):
    parsed = parse_record_date(raw)

    assert parsed.raw == raw
    assert parsed.sort_value == sort_value
    assert parsed.status == "KNOWN"


@pytest.mark.parametrize("raw", ["2026-02-30", "24.13.1", "日期不清", "24年7月19日"])
def test_parse_record_date_keeps_unparseable_source_text(raw):
    parsed = parse_record_date(raw)

    assert parsed.raw == raw
    assert parsed.sort_value is None
    assert parsed.status == "UNPARSED"


def test_parse_record_date_treats_blank_as_unknown_without_inventing_a_date():
    parsed = parse_record_date("  ")

    assert parsed.raw == "  "
    assert parsed.sort_value is None
    assert parsed.status == "UNKNOWN"
