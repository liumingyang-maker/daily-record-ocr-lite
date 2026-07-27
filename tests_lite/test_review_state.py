from __future__ import annotations

import pytest

from lite_app.final_result import FinalResultService
from lite_app.review_editor import ReviewEditor, ReviewInputError
from lite_app.review_state import ReviewStateStore, confirm_formula
from tests_lite.review_fixtures import make_review_final

FORMULA_ID = "job-state__page_001__formula_001"


def _editor(tmp_path, *, missing: str | None = None) -> ReviewEditor:
    final = make_review_final("job-state")
    page = final["pages"][0]
    section = page["product_sections"][0]
    formula = section["formulas"][0]
    formula["record_date"]["value"] = "2026-07-27"
    formula["materials"][0]["amount"]["status"] = "AUTO_ACCEPT"
    targets = {
        "customer": (page["company"], "standard_value"),
        "product": (section["product_or_series"], "value"),
        "date": (formula["record_date"], "value"),
        "material_name": (formula["materials"][0]["name"], "value"),
        "material_amount": (formula["materials"][0]["amount"], "value"),
    }
    if missing:
        target, key = targets[missing]
        target[key] = ""
        if missing == "customer":
            target["raw_value"] = ""
    FinalResultService(tmp_path).save(final)
    return ReviewEditor(tmp_path)


def test_formula_confirmation_marks_visible_values_and_records_hash(tmp_path):
    editor = _editor(tmp_path)
    store = ReviewStateStore(tmp_path)

    result = confirm_formula(editor, store, FORMULA_ID, _version(editor))

    assert result["confirmed"] is True
    final = editor.load()
    assert store.is_confirmed(final, FORMULA_ID) is True
    formula = final["pages"][0]["product_sections"][0]["formulas"][0]
    assert formula["record_date"]["status"] == "MANUAL_CONFIRMED"
    assert formula["materials"][0]["unit"]["status"] == "MANUAL_CONFIRMED_EMPTY"
    assert formula["notes"]["status"] == "MANUAL_CONFIRMED_EMPTY"


def test_edit_invalidates_confirmation(tmp_path):
    editor = _editor(tmp_path)
    store = ReviewStateStore(tmp_path)
    final = editor.load()
    store.confirm(final, FORMULA_ID)

    editor.update_formula(
        FORMULA_ID,
        {"record_date": "2026-07-28"},
        expected_version=final["updated_at"],
    )

    assert store.is_confirmed(editor.load(), FORMULA_ID) is False


@pytest.mark.parametrize(
    ("missing", "label"),
    [
        ("customer", "客户"),
        ("product", "产品"),
        ("date", "日期"),
        ("material_name", "材料名称"),
        ("material_amount", "材料数量"),
    ],
)
def test_formula_confirmation_rejects_missing_required_business_values(
    tmp_path, missing, label
):
    editor = _editor(tmp_path, missing=missing)

    with pytest.raises(ReviewInputError, match=label):
        confirm_formula(
            editor,
            ReviewStateStore(tmp_path),
            FORMULA_ID,
            _version(editor),
        )


def _version(editor: ReviewEditor) -> str:
    return str(editor.load()["updated_at"])
