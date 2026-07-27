"""Stable fingerprints and provenance-preserving formula deduplication."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from .import_models import FormulaCandidate


@dataclass(frozen=True)
class FormulaSourceRecord:
    formula: FormulaCandidate
    source_path: str
    cell_range: str


@dataclass(frozen=True)
class DeduplicatedFormula:
    fingerprint: str
    formula: FormulaCandidate
    sources: tuple[FormulaSourceRecord, ...]


def formula_fingerprint(formula: FormulaCandidate) -> str:
    """Return a content hash that excludes source position and display numbering."""
    payload = {
        "customer": _normalize(formula.customer),
        "product": _normalize(formula.product),
        "record_date": formula.record_date or "",
        "materials": [
            {
                "name": _normalize(item.name_raw),
                "amount": _normalize(item.amount_raw),
            }
            for item in formula.materials
        ],
        "process": [
            {
                "name": _normalize(item.name_raw),
                "value": _normalize(item.value_raw),
            }
            for item in formula.process_parameters
        ],
        "notes": _normalize(formula.notes_raw),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deduplicate_formulas(
    records: Iterable[FormulaSourceRecord],
) -> tuple[DeduplicatedFormula, ...]:
    """Group exact content duplicates and retain every unique provenance entry."""
    groups: dict[str, list[FormulaSourceRecord]] = {}
    for record in records:
        groups.setdefault(formula_fingerprint(record.formula), []).append(record)

    result: list[DeduplicatedFormula] = []
    for fingerprint in sorted(groups):
        source_records = groups[fingerprint]
        unique: list[FormulaSourceRecord] = []
        seen: set[tuple[str, str]] = set()
        for record in source_records:
            key = (record.source_path, record.cell_range)
            if key not in seen:
                seen.add(key)
                unique.append(record)
        result.append(
            DeduplicatedFormula(
                fingerprint=fingerprint,
                formula=source_records[0].formula,
                sources=tuple(unique),
            )
        )
    return tuple(result)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", text).strip().casefold()
