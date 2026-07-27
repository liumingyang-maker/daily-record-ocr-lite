"""Versioned structural editing of the canonical FinalResult."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from .final_result import FinalResultError, FinalResultService
from .storage import read_json_optional, write_json_atomic

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ReviewVersionConflict(RuntimeError):
    """The browser submitted an obsolete FinalResult version."""


class ReviewInputError(ValueError):
    """A structural edit contains unsupported or invalid business data."""


class ReviewEditor:
    def __init__(self, job_dir) -> None:
        self.job_dir = job_dir
        self.service = FinalResultService(job_dir)
        self.undo_path = job_dir / "review" / "undo.json"
        self.corrections_path = job_dir / "review" / "editor_corrections.json"

    def load(self) -> dict[str, Any]:
        return self.service.load()

    def update_identity(
        self,
        group_id: str,
        *,
        customer: str,
        product: str,
        expected_version: str,
    ) -> None:
        def edit(final: dict[str, Any]) -> None:
            _page, section = _find_section(final, group_id)
            company = _page["company"]
            company.update(
                {
                    "raw_value": str(customer),
                    "standard_value": str(customer),
                    "confidence": 1.0,
                    "evidence_token_ids": [],
                    "match_source": "manual",
                    "review_status": _manual_status(customer),
                }
            )
            _update_manual_field(section["product_or_series"], str(product))

        self._mutate(expected_version, "update_identity", edit)

    def add_formula(self, group_id: str, *, expected_version: str) -> str:
        formula_id = f"formula_{uuid4().hex}"

        def edit(final: dict[str, Any]) -> str:
            page, section = _find_section(final, group_id)
            formulas = section["formulas"]
            sequence = len(formulas) + 1
            image_index = int(page.get("source_image_index", 1))
            record_bbox = section.get("section_bbox")
            formulas.append(
                {
                    "formula_id": formula_id,
                    "formula_no": f"配方{sequence}",
                    "formula_sequence": sequence,
                    "record_date": _manual_field(
                        "",
                        f"{formula_id}__record_date",
                        image_index,
                        record_bbox,
                    ),
                    "record_bbox": record_bbox,
                    "materials": [],
                    "process_parameters": [],
                    "notes": _manual_field(
                        "", f"{formula_id}__notes", image_index, record_bbox
                    ),
                    "warnings": [],
                    "confidence": 1.0,
                }
            )
            _resequence(formulas)
            return formula_id

        return self._mutate(expected_version, "add_formula", edit)

    def update_formula(
        self,
        formula_id: str,
        changes: dict[str, str],
        *,
        expected_version: str,
    ) -> None:
        _reject_unknown(changes, {"formula_no", "record_date", "notes"})
        if "record_date" in changes and changes["record_date"] and not _is_iso_date(
            str(changes["record_date"])
        ):
            raise ReviewInputError("日期必须使用 YYYY-MM-DD 格式")

        def edit(final: dict[str, Any]) -> None:
            _page, _section, formula = find_identity_and_formula(final, formula_id)
            if "formula_no" in changes:
                formula["formula_no"] = str(changes["formula_no"])
            if "record_date" in changes:
                _update_manual_field(formula["record_date"], str(changes["record_date"]))
            if "notes" in changes:
                _update_manual_field(formula["notes"], str(changes["notes"]))

        self._mutate(expected_version, "update_formula", edit)

    def delete_formula(self, formula_id: str, *, expected_version: str) -> None:
        snapshot: dict[str, Any] = {}

        def edit(final: dict[str, Any]) -> None:
            _page, section, formula = find_identity_and_formula(final, formula_id)
            formulas = section["formulas"]
            index = formulas.index(formula)
            snapshot.update(
                {"kind": "formula", "group_id": section["section_id"], "index": index, "value": formula}
            )
            formulas.pop(index)
            _resequence(formulas)

        self._mutate(expected_version, "delete_formula", edit, snapshot=snapshot)

    def add_material(
        self,
        formula_id: str,
        values: dict[str, str],
        *,
        expected_version: str,
    ) -> str:
        _reject_unknown(values, {"name", "amount", "unit"})
        material_id = f"material_{uuid4().hex}"

        def edit(final: dict[str, Any]) -> str:
            page, _section, formula = find_identity_and_formula(final, formula_id)
            formula["materials"].append(
                _new_material(material_id, values, page, formula)
            )
            return material_id

        return self._mutate(expected_version, "add_material", edit)

    def update_material(
        self,
        formula_id: str,
        material_id: str,
        changes: dict[str, str],
        *,
        expected_version: str,
    ) -> None:
        _reject_unknown(changes, {"name", "amount", "unit"})

        def edit(final: dict[str, Any]) -> None:
            _page, _section, formula = find_identity_and_formula(final, formula_id)
            material = _find_resource(formula["materials"], "material_id", material_id, "材料")
            for key, value in changes.items():
                _update_manual_field(material[key], str(value))

        self._mutate(expected_version, "update_material", edit)

    def reorder_materials(
        self,
        formula_id: str,
        material_ids: list[str],
        *,
        expected_version: str,
    ) -> None:
        def edit(final: dict[str, Any]) -> None:
            _page, _section, formula = find_identity_and_formula(final, formula_id)
            materials = formula["materials"]
            existing = [str(item["material_id"]) for item in materials]
            if len(set(material_ids)) != len(material_ids) or set(material_ids) != set(existing):
                raise ReviewInputError("材料排序必须包含当前全部材料且不能重复")
            by_id = {str(item["material_id"]): item for item in materials}
            formula["materials"] = [by_id[item_id] for item_id in material_ids]

        self._mutate(expected_version, "reorder_materials", edit)

    def delete_material(
        self,
        formula_id: str,
        material_id: str,
        *,
        expected_version: str,
    ) -> None:
        snapshot: dict[str, Any] = {}

        def edit(final: dict[str, Any]) -> None:
            _page, _section, formula = find_identity_and_formula(final, formula_id)
            material = _find_resource(formula["materials"], "material_id", material_id, "材料")
            index = formula["materials"].index(material)
            snapshot.update(
                {"kind": "material", "formula_id": formula_id, "index": index, "value": material}
            )
            formula["materials"].pop(index)

        self._mutate(expected_version, "delete_material", edit, snapshot=snapshot)

    def add_process_parameter(
        self,
        formula_id: str,
        values: dict[str, str],
        *,
        expected_version: str,
    ) -> str:
        _reject_unknown(values, {"name", "value", "unit"})
        parameter_id = f"parameter_{uuid4().hex}"

        def edit(final: dict[str, Any]) -> str:
            page, _section, formula = find_identity_and_formula(final, formula_id)
            formula["process_parameters"].append(
                _new_parameter(parameter_id, values, page, formula)
            )
            return parameter_id

        return self._mutate(expected_version, "add_process_parameter", edit)

    def update_process_parameter(
        self,
        formula_id: str,
        parameter_id: str,
        changes: dict[str, str],
        *,
        expected_version: str,
    ) -> None:
        _reject_unknown(changes, {"name", "value", "unit"})

        def edit(final: dict[str, Any]) -> None:
            _page, _section, formula = find_identity_and_formula(final, formula_id)
            parameter = _find_resource(
                formula["process_parameters"], "parameter_id", parameter_id, "工艺"
            )
            for key, value in changes.items():
                _update_manual_field(parameter[key], str(value))

        self._mutate(expected_version, "update_process_parameter", edit)

    def delete_process_parameter(
        self,
        formula_id: str,
        parameter_id: str,
        *,
        expected_version: str,
    ) -> None:
        snapshot: dict[str, Any] = {}

        def edit(final: dict[str, Any]) -> None:
            _page, _section, formula = find_identity_and_formula(final, formula_id)
            parameter = _find_resource(
                formula["process_parameters"], "parameter_id", parameter_id, "工艺"
            )
            index = formula["process_parameters"].index(parameter)
            snapshot.update(
                {"kind": "process", "formula_id": formula_id, "index": index, "value": parameter}
            )
            formula["process_parameters"].pop(index)

        self._mutate(expected_version, "delete_process_parameter", edit, snapshot=snapshot)

    def undo_last_delete(self, *, expected_version: str) -> None:
        snapshot = read_json_optional(self.undo_path)
        if not isinstance(snapshot, dict) or not snapshot.get("kind"):
            raise ReviewInputError("没有可撤销的删除操作")

        def edit(final: dict[str, Any]) -> None:
            kind = snapshot["kind"]
            index = int(snapshot["index"])
            value = snapshot["value"]
            if kind == "formula":
                _page, section = _find_section(final, str(snapshot["group_id"]))
                section["formulas"].insert(index, value)
                _resequence(section["formulas"])
                return
            _page, _section, formula = find_identity_and_formula(
                final, str(snapshot["formula_id"])
            )
            target = formula["materials"] if kind == "material" else formula["process_parameters"]
            target.insert(index, value)

        self._mutate(expected_version, "undo_delete", edit)
        write_json_atomic(self.undo_path, {})

    def _mutate(
        self,
        expected_version: str,
        action: str,
        callback: Callable[[dict[str, Any]], Any],
        *,
        snapshot: dict[str, Any] | None = None,
    ) -> Any:
        try:
            result, final = self.service.mutate(expected_version, callback)
        except FinalResultError as exc:
            if "另一个窗口" in str(exc):
                raise ReviewVersionConflict(str(exc)) from exc
            raise
        if snapshot:
            write_json_atomic(self.undo_path, snapshot)
        self._append_correction(action, str(final["updated_at"]))
        return result

    def _append_correction(self, action: str, version: str) -> None:
        corrections = read_json_optional(self.corrections_path)
        if not isinstance(corrections, list):
            corrections = []
        corrections.append({"action": action, "version": version})
        write_json_atomic(self.corrections_path, corrections)


def find_identity_and_formula(
    final: dict[str, Any], formula_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for page in final.get("pages", []):
        for section in page.get("product_sections", []):
            for formula in section.get("formulas", []):
                if str(formula.get("formula_id")) == formula_id:
                    return page, section, formula
    raise ReviewInputError(f"配方不存在: {formula_id}")


def _find_section(
    final: dict[str, Any], group_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    for page in final.get("pages", []):
        for section in page.get("product_sections", []):
            if str(section.get("section_id")) == group_id:
                return page, section
    raise ReviewInputError(f"客户产品组不存在: {group_id}")


def _find_resource(items: list[dict], key: str, value: str, label: str) -> dict:
    for item in items:
        if str(item.get(key)) == value:
            return item
    raise ReviewInputError(f"{label}不存在: {value}")


def _reject_unknown(values: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ReviewInputError(f"不支持的字段: {', '.join(unknown)}")


def _is_iso_date(value: str) -> bool:
    if not ISO_DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _manual_status(value: Any) -> str:
    return "MANUAL_CONFIRMED" if str(value).strip() else "MANUAL_CONFIRMED_EMPTY"


def _update_manual_field(field: dict[str, Any], value: str) -> None:
    field.update(
        {
            "value": value,
            "confidence": 1.0,
            "status": _manual_status(value),
            "review_status": _manual_status(value),
            "source": "manual",
            "candidates": [],
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )


def _manual_field(
    value: str,
    field_id: str,
    source_image_index: int,
    record_bbox: list[float] | None,
) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": 1.0,
        "evidence_token_ids": [],
        "bbox": None,
        "field_id": field_id,
        "status": _manual_status(value),
        "review_status": _manual_status(value),
        "source": "manual",
        "candidates": [],
        "source_image_index": source_image_index,
        "record_bbox": record_bbox,
        "recheck_count": 0,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _new_material(
    material_id: str,
    values: dict[str, str],
    page: dict[str, Any],
    formula: dict[str, Any],
) -> dict[str, Any]:
    image_index = int(page.get("source_image_index", 1))
    record_bbox = formula.get("record_bbox")
    return {
        "material_id": material_id,
        **{
            key: _manual_field(
                str(values.get(key, "")),
                f"{formula['formula_id']}__{material_id}__{key}",
                image_index,
                record_bbox,
            )
            for key in ("name", "amount", "unit")
        },
        "warnings": [],
    }


def _new_parameter(
    parameter_id: str,
    values: dict[str, str],
    page: dict[str, Any],
    formula: dict[str, Any],
) -> dict[str, Any]:
    image_index = int(page.get("source_image_index", 1))
    record_bbox = formula.get("record_bbox")
    return {
        "parameter_id": parameter_id,
        **{
            key: _manual_field(
                str(values.get(key, "")),
                f"{formula['formula_id']}__{parameter_id}__{key}",
                image_index,
                record_bbox,
            )
            for key in ("name", "value", "unit")
        },
        "warnings": [],
    }


def _resequence(formulas: list[dict[str, Any]]) -> None:
    for sequence, formula in enumerate(formulas, 1):
        formula["formula_sequence"] = sequence
