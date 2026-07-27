from lite_app.knowledge.formula_extractor import extract_sheet
from lite_app.knowledge.workbook_reader import CellData, SheetData


def _sheet(
    name: str,
    rows: list[list[object | None]],
    *,
    date_cells: set[tuple[int, int]] | None = None,
) -> SheetData:
    dates = date_cells or set()
    cells = tuple(
        CellData(
            row=row_index,
            column=column_index,
            value=value,  # type: ignore[arg-type]
            is_date=(row_index, column_index) in dates,
        )
        for row_index, row in enumerate(rows, 1)
        for column_index, value in enumerate(row, 1)
        if value is not None
    )
    return SheetData(
        name=name,
        max_row=len(rows),
        max_column=max((len(row) for row in rows), default=0),
        cells=cells,
    )


def test_extracts_material_amount_process_date_and_notes() -> None:
    sheet = _sheet(
        "G30A",
        [
            ["G30A", None, "2024-07-12"],
            ["配方", "PA6", "玻纤", "增韧剂"],
            [None, "55", "35-36", "2（加到3%）"],
            ["工艺", "主机", "喂料"],
            [None, "300", "25"],
            ["注意事项", "客户要求保持黑度"],
        ],
    )

    result = extract_sheet(sheet, customer_hint="联创")

    assert result.pending == ()
    assert result.exclusions == ()
    assert len(result.formulas) == 1
    formula = result.formulas[0]
    assert formula.customer == "联创"
    assert formula.product == "G30A"
    assert formula.record_date == "2024-07-12"
    assert [(item.name_raw, item.amount_raw) for item in formula.materials] == [
        ("PA6", "55"),
        ("玻纤", "35-36"),
        ("增韧剂", "2（加到3%）"),
    ]
    assert [
        (item.name_raw, item.value_raw)
        for item in formula.process_parameters
    ] == [("主机", "300"), ("喂料", "25")]
    assert formula.notes_raw == "客户要求保持黑度"


def test_rejects_invalid_formula_but_keeps_classified_terms() -> None:
    sheet = _sheet(
        "G30A",
        [
            ["G30A"],
            ["配方（作废）", "PA6", "玻纤"],
            [None, "55", "35"],
            ["工艺", "主机"],
            [None, "300"],
        ],
    )

    result = extract_sheet(sheet, customer_hint="联创")

    assert result.formulas == ()
    assert result.exclusions[0].reason == "INVALID_FORMULA"
    terms = {(term.term_type, term.value) for term in result.lexicon_terms}
    assert ("customer", "联创") in terms
    assert ("product", "G30A") in terms
    assert ("material", "PA6") in terms
    assert ("material", "玻纤") in terms
    assert ("process", "主机") in terms
    assert all(term.source_quality == "reference" for term in result.lexicon_terms)


def test_unknown_date_remains_a_formal_formula() -> None:
    sheet = _sheet(
        "PPT20",
        [["配方", "PP", "滑石粉"], [None, "80", "20"]],
    )

    result = extract_sheet(sheet, customer_hint="博厚")

    assert len(result.formulas) == 1
    assert result.formulas[0].record_date is None
    assert result.formulas[0].date_status == "UNKNOWN"


def test_stacked_formula_blocks_keep_source_order_and_dates() -> None:
    sheet = _sheet(
        "G30A",
        [
            ["G30A", "2024/01/03"],
            ["配方1", "PA6", "玻纤"],
            [None, "60", "40"],
            ["配方2", "PA6", "玻纤", "增韧剂"],
            [None, "58", "40", "2"],
            ["G30A", "2024/07/12"],
            ["配方3", "PA6", "玻纤"],
            [None, "55", "45"],
        ],
    )

    result = extract_sheet(sheet, customer_hint="联创")

    assert [formula.source_order for formula in result.formulas] == [1, 2, 3]
    assert [formula.formula_label for formula in result.formulas] == [
        "配方1",
        "配方2",
        "配方3",
    ]
    assert [formula.record_date for formula in result.formulas] == [
        "2024-01-03",
        None,
        "2024-07-12",
    ]


def test_unassigned_general_formula_contributes_only_lexicon() -> None:
    sheet = _sheet(
        "603",
        [["配方", "PA6", "玻纤"], [None, "60", "40"]],
    )

    result = extract_sheet(sheet, customer_hint="通用配方")

    assert result.formulas == ()
    assert result.pending == ()
    assert {(term.term_type, term.value) for term in result.lexicon_terms} >= {
        ("product", "603"),
        ("material", "PA6"),
        ("material", "玻纤"),
    }
    assert result.exclusions[0].reason == "UNASSIGNED_GENERAL_FORMULA"


def test_customer_product_conflict_is_pending_with_source_cells() -> None:
    sheet = _sheet(
        "G30A",
        [
            ["PA66G15"],
            ["配方", "PA66", "玻纤"],
            [None, "85", "15"],
        ],
    )

    result = extract_sheet(sheet, customer_hint="联创")

    assert result.formulas == ()
    assert len(result.pending) == 1
    assert result.pending[0].reason == "PRODUCT_CONFLICT"
    assert result.pending[0].start_row == 2
    assert result.pending[0].end_row == 3


def test_previous_process_rows_are_not_the_next_product_title() -> None:
    sheet = _sheet(
        "PA6G30黄",
        [
            ["PA6G30黄"],
            ["配方1", "PA6", "玻纤"],
            [None, "60", "40"],
            ["工艺", "主机（vpm）", "喂料"],
            [None, "300", "25"],
            ["备注", "保持原工艺"],
            ["配方2", "PA6", "玻纤"],
            [None, "58", "42"],
        ],
    )

    result = extract_sheet(sheet, customer_hint="东制")

    assert result.pending == ()
    assert len(result.formulas) == 2
    assert {formula.product for formula in result.formulas} == {"PA6G30黄"}


def test_generic_sheet_inherits_the_last_explicit_product() -> None:
    sheet = _sheet(
        "Sheet1",
        [
            ["JB30"],
            ["配方1", "PA6", "玻纤"],
            [None, "60", "40"],
            ["工艺", "主机"],
            [None, "480"],
            ["2022-10-03"],
            ["配方2", "PA6", "玻纤"],
            [None, "58", "42"],
        ],
    )

    result = extract_sheet(sheet, customer_hint="七盛")

    assert result.pending == ()
    assert [formula.product for formula in result.formulas] == ["JB30", "JB30"]


def test_blank_formula_template_is_excluded_instead_of_pending() -> None:
    sheet = _sheet(
        "G30A",
        [
            ["G30A"],
            ["配方"],
            [],
            ["工艺", "主机", "喂料"],
            [],
        ],
    )

    result = extract_sheet(sheet, customer_hint="联创")

    assert result.formulas == ()
    assert result.pending == ()
    assert result.exclusions[0].reason == "EMPTY_TEMPLATE"
