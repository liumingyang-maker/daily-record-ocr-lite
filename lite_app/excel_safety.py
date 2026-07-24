"""Prevent untrusted OCR/Vision text from becoming executable Excel formulas."""

from __future__ import annotations

from typing import Any

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_excel_value(value: Any) -> Any:
    """Force formula-looking strings to remain literal cell text."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value
