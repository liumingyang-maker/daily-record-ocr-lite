from __future__ import annotations

import pytest

from lite_app.final_result import FinalResultService
from lite_app.readiness import validate_final_result_contract
from lite_app.review_editor import ReviewEditor, ReviewInputError, ReviewVersionConflict
from tests_lite.review_fixtures import make_review_final


def _make_editor(tmp_path) -> ReviewEditor:
    service = FinalResultService(tmp_path)
    service.save(make_review_final("job-editor"))
    return ReviewEditor(tmp_path)


def _version(editor: ReviewEditor) -> str:
    return str(editor.load()["updated_at"])


def _assert_valid(editor: ReviewEditor) -> dict:
    final = editor.load()
    assert validate_final_result_contract(final).issues == []
    return final


def test_editor_mutates_canonical_formula_structure_and_keeps_schema_valid(tmp_path):
    editor = _make_editor(tmp_path)
    group_id = "section_001"

    editor.update_identity(
        group_id,
        customer="联创新客户",
        product="G30A-H",
        expected_version=_version(editor),
    )
    final = _assert_valid(editor)
    assert final["pages"][0]["company"]["standard_value"] == "联创新客户"
    assert final["pages"][0]["product_sections"][0]["product_or_series"]["value"] == "G30A-H"

    formula_id = editor.add_formula(group_id, expected_version=_version(editor))
    final = _assert_valid(editor)
    formulas = final["pages"][0]["product_sections"][0]["formulas"]
    assert formulas[-1]["formula_id"] == formula_id
    assert [item["formula_sequence"] for item in formulas] == [1, 2]
    editor.update_formula(
        formula_id,
        {"record_date": "2026-07-27", "formula_no": "配方2"},
        expected_version=_version(editor),
    )
    assert _formula(_assert_valid(editor), formula_id)["record_date"]["value"] == "2026-07-27"

    existing_id = formulas[-1]["materials"][0]["material_id"] if formulas[-1]["materials"] else None
    material_id = editor.add_material(
        formula_id,
        {"name": "PA66", "amount": "60", "unit": "kg"},
        expected_version=_version(editor),
    )
    final = _assert_valid(editor)
    formula = _formula(final, formula_id)
    assert formula["materials"][-1]["material_id"] == material_id

    editor.update_material(
        formula_id,
        material_id,
        {"amount": "62"},
        expected_version=_version(editor),
    )
    assert _formula(_assert_valid(editor), formula_id)["materials"][-1]["amount"]["value"] == "62"

    if existing_id is None:
        existing_id = editor.add_material(
            formula_id,
            {"name": "色粉", "amount": "1", "unit": "kg"},
            expected_version=_version(editor),
        )
    editor.reorder_materials(
        formula_id,
        [material_id, existing_id],
        expected_version=_version(editor),
    )
    assert [
        item["material_id"] for item in _formula(_assert_valid(editor), formula_id)["materials"]
    ] == [material_id, existing_id]

    parameter_id = editor.add_process_parameter(
        formula_id,
        {"name": "温度", "value": "260", "unit": "℃"},
        expected_version=_version(editor),
    )
    assert _formula(_assert_valid(editor), formula_id)["process_parameters"][0][
        "parameter_id"
    ] == parameter_id
    editor.update_process_parameter(
        formula_id,
        parameter_id,
        {"value": "265"},
        expected_version=_version(editor),
    )
    assert _formula(_assert_valid(editor), formula_id)["process_parameters"][0]["value"][
        "value"
    ] == "265"

    editor.delete_process_parameter(formula_id, parameter_id, expected_version=_version(editor))
    assert _formula(_assert_valid(editor), formula_id)["process_parameters"] == []
    editor.delete_material(formula_id, material_id, expected_version=_version(editor))
    assert len(_formula(_assert_valid(editor), formula_id)["materials"]) == 1
    editor.delete_formula(formula_id, expected_version=_version(editor))
    final = _assert_valid(editor)
    assert [item["formula_sequence"] for item in final["pages"][0]["product_sections"][0]["formulas"]] == [1]


def test_editor_rejects_stale_version_and_invalid_or_unknown_values(tmp_path):
    editor = _make_editor(tmp_path)
    stale = _version(editor)
    editor.update_identity(
        "section_001", customer="联创", product="G30A", expected_version=stale
    )

    with pytest.raises(ReviewVersionConflict):
        editor.add_formula("section_001", expected_version=stale)
    with pytest.raises(ReviewInputError, match="日期"):
        editor.update_formula(
            "job-editor__page_001__formula_001",
            {"record_date": "2026/07/27"},
            expected_version=_version(editor),
        )
    with pytest.raises(ReviewInputError, match="日期"):
        editor.update_formula(
            "job-editor__page_001__formula_001",
            {"record_date": "2026-02-30"},
            expected_version=_version(editor),
        )
    with pytest.raises(ReviewInputError, match="不支持"):
        editor.update_material(
            "job-editor__page_001__formula_001",
            "material_001",
            {"internal_status": "AUTO_ACCEPT"},
            expected_version=_version(editor),
        )


def test_editor_undo_restores_last_deleted_material(tmp_path):
    editor = _make_editor(tmp_path)
    formula_id = "job-editor__page_001__formula_001"
    material_id = "material_001"

    editor.delete_material(formula_id, material_id, expected_version=_version(editor))
    assert _formula(_assert_valid(editor), formula_id)["materials"] == []
    editor.undo_last_delete(expected_version=_version(editor))

    material = _formula(_assert_valid(editor), formula_id)["materials"][0]
    assert material["material_id"] == material_id
    assert material["name"]["value"] == "PA66"


def _formula(final: dict, formula_id: str) -> dict:
    return next(
        formula
        for page in final["pages"]
        for section in page["product_sections"]
        for formula in section["formulas"]
        if formula["formula_id"] == formula_id
    )
