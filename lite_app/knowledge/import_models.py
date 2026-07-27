"""Immutable contracts shared by legacy extraction and knowledge import."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TermType = Literal["customer", "product", "material", "process", "note_phrase"]
SourceQuality = Literal["candidate", "confirmed", "reference"]


@dataclass(frozen=True)
class MaterialCandidate:
    name_raw: str
    amount_raw: str
    column: int


@dataclass(frozen=True)
class ProcessParameterCandidate:
    name_raw: str
    value_raw: str
    column: int


@dataclass(frozen=True)
class SourceSpan:
    sheet_name: str
    start_row: int
    end_row: int
    start_column: int
    end_column: int


@dataclass(frozen=True)
class FormulaCandidate:
    customer: str
    product: str
    record_date: str | None
    date_status: Literal["KNOWN", "UNKNOWN"]
    source_order: int
    formula_label: str
    materials: tuple[MaterialCandidate, ...]
    process_parameters: tuple[ProcessParameterCandidate, ...]
    notes_raw: str
    confidence: float
    source_span: SourceSpan


@dataclass(frozen=True)
class LexiconTermCandidate:
    term_type: TermType
    value: str
    source_quality: SourceQuality
    customer_context: str = ""
    product_context: str = ""
    row: int = 0
    column: int = 0


@dataclass(frozen=True)
class ExtractionIssue:
    reason: str
    start_row: int
    end_row: int
    details: str = ""
    formula: FormulaCandidate | None = None


@dataclass(frozen=True)
class SheetExtraction:
    formulas: tuple[FormulaCandidate, ...] = ()
    pending: tuple[ExtractionIssue, ...] = ()
    exclusions: tuple[ExtractionIssue, ...] = ()
    lexicon_terms: tuple[LexiconTermCandidate, ...] = ()
