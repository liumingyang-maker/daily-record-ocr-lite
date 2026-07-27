from pathlib import Path

from PIL import Image

from lite_app.knowledge.evidence_renderer import render_formula_evidence
from lite_app.knowledge.import_models import (
    FormulaCandidate,
    MaterialCandidate,
    SourceSpan,
)
from lite_app.knowledge.import_records import (
    FormulaSourceRecord,
    deduplicate_formulas,
    formula_fingerprint,
)
from lite_app.knowledge.workbook_reader import CellData, SheetData


def _formula(*, date: str | None = "2024-07-12") -> FormulaCandidate:
    return FormulaCandidate(
        customer="联创",
        product="G30A",
        record_date=date,
        date_status="KNOWN" if date else "UNKNOWN",
        source_order=1,
        formula_label="配方1",
        materials=(
            MaterialCandidate("PA6", "55", 2),
            MaterialCandidate("玻纤", "35-36", 3),
        ),
        process_parameters=(),
        notes_raw="客户要求保持黑度",
        confidence=0.95,
        source_span=SourceSpan("G30A", 2, 4, 1, 3),
    )


def _sheet() -> SheetData:
    rows = [
        ["G30A", None, "2024-07-12"],
        ["配方1", "PA6", "玻纤"],
        [None, "55", "35-36"],
        ["注意事项", "客户要求保持黑度"],
        ["下一条记录"],
    ]
    cells = tuple(
        CellData(row_index, column_index, value)  # type: ignore[arg-type]
        for row_index, row in enumerate(rows, 1)
        for column_index, value in enumerate(row, 1)
        if value is not None
    )
    return SheetData("G30A", len(rows), 3, cells)


def test_formula_fingerprint_is_stable_and_date_sensitive() -> None:
    first = formula_fingerprint(_formula())
    same = formula_fingerprint(_formula())
    different_date = formula_fingerprint(_formula(date="2024-07-13"))

    assert first == same
    assert len(first) == 64
    assert first != different_date


def test_duplicate_formula_merges_sources_but_not_dates() -> None:
    records = [
        FormulaSourceRecord(_formula(), "联创/联创.xlsx", "G30A!A2:C4"),
        FormulaSourceRecord(_formula(), "联创/备份.xlsx", "G30A!A2:C4"),
        FormulaSourceRecord(
            _formula(date="2024-07-13"),
            "联创/联创.xlsx",
            "G30A!A7:C9",
        ),
    ]

    groups = deduplicate_formulas(records)

    assert len(groups) == 2
    merged = next(group for group in groups if len(group.sources) == 2)
    assert {source.source_path for source in merged.sources} == {
        "联创/联创.xlsx",
        "联创/备份.xlsx",
    }


def test_renders_tight_and_context_png_with_hashed_names(tmp_path: Path) -> None:
    rendered = render_formula_evidence(
        _sheet(),
        _formula(),
        tmp_path,
        source_id="联创/联创.xlsx",
    )

    assert rendered.tight_path.exists()
    assert rendered.context_path.exists()
    assert "联创" not in rendered.tight_path.name
    assert "G30A" not in rendered.tight_path.name
    with Image.open(rendered.tight_path) as tight:
        assert tight.format == "PNG"
        assert tight.width > 100
        assert tight.height > 50
    with Image.open(rendered.context_path) as context:
        assert context.height > tight.height
