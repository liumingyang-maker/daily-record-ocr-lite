"""Conservative state-machine extraction for legacy formula worksheets."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from typing import Iterable

from openpyxl.utils.datetime import from_excel

from .import_models import (
    ExtractionIssue,
    FormulaCandidate,
    LexiconTermCandidate,
    MaterialCandidate,
    ProcessParameterCandidate,
    SheetExtraction,
    SourceQuality,
    SourceSpan,
    TermType,
)
from .workbook_reader import CellData, CellValue, SheetData

FORMULA_PATTERN = re.compile(r"^配方(?:\s*[\d一二三四五六七八九十]+)?(?:[:：])?")
INVALID_FORMULA_MARKERS = ("失败", "废弃", "作废", "无效")
GENERIC_SHEET_NAMES = {"sheet", "sheet1", "汇总", "总表", "配方", "配方表"}
ROW_LABELS = {
    "配方",
    "数量",
    "用量",
    "工艺",
    "注意",
    "注意事项",
    "备注",
    "日期",
}
DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|[./-])\s*"
    r"(?P<month>\d{1,2})\s*(?:月|[./-])\s*"
    r"(?P<day>\d{1,2})\s*日?"
)
COMPACT_DATE_PATTERN = re.compile(r"^(20\d{2})(\d{2})(\d{2})$")


def extract_sheet(sheet: SheetData, customer_hint: str) -> SheetExtraction:
    """Extract formula blocks and typed lexicon terms from one worksheet."""
    anchors = [
        cell
        for cell in sheet.cells
        if isinstance(cell.value, str)
        and FORMULA_PATTERN.match(_clean_text(cell.value))
    ]
    anchors.sort(key=lambda cell: (cell.row, cell.column))
    if not anchors:
        return SheetExtraction()

    formulas: list[FormulaCandidate] = []
    pending: list[ExtractionIssue] = []
    exclusions: list[ExtractionIssue] = []
    terms: list[LexiconTermCandidate] = []
    customer = _clean_text(customer_hint)
    unassigned_general = customer in {"", "通用配方"}
    sheet_product = _sheet_product(sheet.name)
    last_product = sheet_product

    for source_order, anchor in enumerate(anchors, 1):
        previous_anchor = anchors[source_order - 2] if source_order > 1 else None
        next_anchor = (
            anchors[source_order]
            if source_order < len(anchors)
            else None
        )
        end_row = next_anchor.row - 1 if next_anchor else sheet.max_row
        date_scope_start = (
            previous_anchor.row + 2
            if previous_anchor
            else max(1, anchor.row - 3)
        )
        title, record_date = _title_and_date(
            sheet,
            start_row=date_scope_start,
            end_row=anchor.row - 1,
            allow_undated_title=previous_anchor is None,
        )
        product = title or sheet_product or last_product
        if product:
            last_product = product
        block_cells = tuple(
            cell
            for cell in sheet.cells
            if anchor.row <= cell.row <= end_row
        )
        materials, amount_row = _extract_materials(sheet, anchor, end_row)
        process, process_rows = _extract_process(sheet, amount_row, end_row)
        notes = _extract_notes(
            sheet,
            start_row=amount_row + 1,
            end_row=end_row,
            excluded_rows=process_rows,
            product=product,
        )
        span = SourceSpan(
            sheet_name=sheet.name,
            start_row=anchor.row,
            end_row=max(anchor.row, end_row),
            start_column=anchor.column,
            end_column=max(
                [anchor.column]
                + [item.column for item in materials]
                + [item.column for item in process],
            ),
        )
        formula = FormulaCandidate(
            customer=customer,
            product=product,
            record_date=record_date,
            date_status="KNOWN" if record_date else "UNKNOWN",
            source_order=source_order,
            formula_label=_clean_text(anchor.value),
            materials=materials,
            process_parameters=process,
            notes_raw=notes,
            confidence=0.95,
            source_span=span,
        )

        invalid = _contains_invalid_marker(block_cells)
        conflict = bool(
            title
            and sheet_product
            and _normalize_name(title) != _normalize_name(sheet_product)
        )
        empty_template = not materials
        missing_structure = bool(materials) and not any(
            item.amount_raw for item in materials
        )

        if invalid:
            exclusions.append(
                ExtractionIssue(
                    reason="INVALID_FORMULA",
                    start_row=anchor.row,
                    end_row=end_row,
                )
            )
            terms.extend(_formula_terms(formula, "reference"))
            continue
        if empty_template:
            exclusions.append(
                ExtractionIssue(
                    reason="EMPTY_TEMPLATE",
                    start_row=anchor.row,
                    end_row=end_row,
                )
            )
            terms.extend(_formula_terms(formula, "reference"))
            continue
        if unassigned_general:
            exclusions.append(
                ExtractionIssue(
                    reason="UNASSIGNED_GENERAL_FORMULA",
                    start_row=anchor.row,
                    end_row=end_row,
                )
            )
            terms.extend(
                _formula_terms(
                    replace(formula, customer=""),
                    "reference",
                )
            )
            continue
        if conflict:
            pending.append(
                ExtractionIssue(
                    reason="PRODUCT_CONFLICT",
                    start_row=anchor.row,
                    end_row=end_row,
                    details=f"sheet={sheet_product}; title={title}",
                    formula=formula,
                )
            )
            terms.extend(_formula_terms(formula, "candidate"))
            continue
        if not product or missing_structure:
            pending.append(
                ExtractionIssue(
                    reason=(
                        "MISSING_PRODUCT"
                        if not product
                        else "INCOMPLETE_FORMULA_STRUCTURE"
                    ),
                    start_row=anchor.row,
                    end_row=end_row,
                    formula=formula,
                )
            )
            terms.extend(_formula_terms(formula, "candidate"))
            continue

        formulas.append(formula)
        terms.extend(_formula_terms(formula, "candidate"))

    return SheetExtraction(
        formulas=tuple(formulas),
        pending=tuple(pending),
        exclusions=tuple(exclusions),
        lexicon_terms=_dedupe_terms(terms),
    )


def _extract_materials(
    sheet: SheetData,
    anchor: CellData,
    end_row: int,
) -> tuple[tuple[MaterialCandidate, ...], int]:
    material_cells = [
        cell
        for cell in sheet.row_cells(anchor.row)
        if cell.column > anchor.column and _text(cell.value)
    ]
    if not material_cells:
        return (), min(anchor.row + 1, end_row)

    amount_row = anchor.row + 1
    for row in range(anchor.row + 1, min(end_row, anchor.row + 3) + 1):
        if any(_text(sheet.value_at(row, cell.column)) for cell in material_cells):
            amount_row = row
            break

    materials = tuple(
        MaterialCandidate(
            name_raw=_text(cell.value),
            amount_raw=_text(sheet.value_at(amount_row, cell.column)),
            column=cell.column,
        )
        for cell in material_cells
        if _text(cell.value) not in ROW_LABELS
    )
    return materials, amount_row


def _extract_process(
    sheet: SheetData,
    amount_row: int,
    end_row: int,
) -> tuple[tuple[ProcessParameterCandidate, ...], set[int]]:
    for row in range(amount_row + 1, end_row + 1):
        row_cells = sheet.row_cells(row)
        anchor = next(
            (
                cell
                for cell in row_cells
                if _text(cell.value).startswith("工艺")
            ),
            None,
        )
        if anchor is None:
            continue
        value_row = min(row + 1, end_row)
        parameters = tuple(
            ProcessParameterCandidate(
                name_raw=_text(cell.value),
                value_raw=_text(sheet.value_at(value_row, cell.column)),
                column=cell.column,
            )
            for cell in row_cells
            if cell.column > anchor.column and _text(cell.value)
        )
        return parameters, {row, value_row}
    return (), set()


def _extract_notes(
    sheet: SheetData,
    start_row: int,
    end_row: int,
    excluded_rows: set[int],
    product: str,
) -> str:
    notes: list[str] = []
    for row in range(start_row, end_row + 1):
        if row in excluded_rows:
            continue
        values = [_text(cell.value) for cell in sheet.row_cells(row)]
        values = [value for value in values if value]
        if not values or any(_parse_date(value) for value in values):
            continue
        if len(values) == 1 and _normalize_name(values[0]) == _normalize_name(product):
            continue
        if FORMULA_PATTERN.match(values[0]):
            continue
        if values[0] in {"注意", "注意事项", "备注"}:
            values = values[1:]
        if values:
            notes.append(" ".join(values))
    return "\n".join(dict.fromkeys(notes))


def _title_and_date(
    sheet: SheetData,
    start_row: int,
    end_row: int,
    allow_undated_title: bool,
) -> tuple[str, str | None]:
    title = ""
    record_date: str | None = None
    for row in range(max(1, start_row), end_row + 1):
        row_cells = sheet.row_cells(row)
        row_date = next(
            (
                parsed
                for cell in row_cells
                if (parsed := _cell_date(cell)) is not None
            ),
            None,
        )
        if record_date is None and row_date is not None:
            record_date = row_date
        if title or (not allow_undated_title and row_date is None):
            continue
        for cell in row_cells:
            value = _text(cell.value)
            if (
                value
                and not _cell_date(cell)
                and not FORMULA_PATTERN.match(value)
                and value not in ROW_LABELS
                and not _looks_numeric(value)
            ):
                title = value
    return title, record_date


def _cell_date(cell: CellData) -> str | None:
    if cell.is_date:
        return _parse_date(cell.value)
    value = cell.value
    if isinstance(value, (int, float)) and 30000 <= float(value) <= 60000:
        converted = from_excel(float(value))
        return converted.date().isoformat() if isinstance(converted, datetime) else converted.isoformat()
    return _parse_date(value)


def _parse_date(value: CellValue) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        return parsed.isoformat()
    match = DATE_PATTERN.search(text)
    if match:
        try:
            return date(
                int(match["year"]),
                int(match["month"]),
                int(match["day"]),
            ).isoformat()
        except ValueError:
            return None
    compact = COMPACT_DATE_PATTERN.match(text)
    if compact:
        try:
            return date(
                int(compact.group(1)),
                int(compact.group(2)),
                int(compact.group(3)),
            ).isoformat()
        except ValueError:
            return None
    return None


def _formula_terms(
    formula: FormulaCandidate,
    quality: SourceQuality,
) -> list[LexiconTermCandidate]:
    terms: list[LexiconTermCandidate] = []

    def add(
        term_type: TermType,
        value: str,
        row: int = 0,
        column: int = 0,
    ) -> None:
        cleaned = _clean_text(value)
        if cleaned:
            terms.append(
                LexiconTermCandidate(
                    term_type=term_type,
                    value=cleaned,
                    source_quality=quality,
                    customer_context=formula.customer,
                    product_context=formula.product,
                    row=row,
                    column=column,
                )
            )

    add("customer", formula.customer)
    add("product", formula.product)
    for material in formula.materials:
        add("material", material.name_raw, formula.source_span.start_row, material.column)
    for parameter in formula.process_parameters:
        add("process", parameter.name_raw, formula.source_span.start_row, parameter.column)
    if formula.notes_raw and len(formula.notes_raw) <= 80:
        add("note_phrase", formula.notes_raw)
    return terms


def _dedupe_terms(
    terms: Iterable[LexiconTermCandidate],
) -> tuple[LexiconTermCandidate, ...]:
    result: list[LexiconTermCandidate] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for term in terms:
        key = (
            term.term_type,
            _normalize_name(term.value),
            term.source_quality,
            _normalize_name(term.customer_context),
            _normalize_name(term.product_context),
        )
        if key not in seen:
            seen.add(key)
            result.append(term)
    return tuple(result)


def _contains_invalid_marker(cells: Iterable[CellData]) -> bool:
    text = " ".join(_text(cell.value) for cell in cells)
    return any(marker in text for marker in INVALID_FORMULA_MARKERS)


def _sheet_product(name: str) -> str:
    value = _clean_text(name)
    if _normalize_name(value) in GENERIC_SHEET_NAMES:
        return ""
    return value


def _clean_text(value: object) -> str:
    return str(value).replace("\u3000", " ").strip()


def _text(value: CellValue) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _clean_text(value)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _looks_numeric(value: str) -> bool:
    return bool(re.fullmatch(r"[\d.\-+%（）()]+", value))
