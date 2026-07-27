"""Durable whole-formula confirmation state."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .review_editor import ReviewEditor, ReviewInputError, find_identity_and_formula
from .storage import read_json_optional, write_json_atomic

STATE_SCHEMA_VERSION = 1


class ReviewStateStore:
    def __init__(self, job_dir: Path) -> None:
        self.path = job_dir / "review" / "review_state.json"

    def confirm(self, final: dict[str, Any], formula_id: str) -> dict[str, Any]:
        state = self._load()
        entry = {
            "content_hash": formula_content_hash(final, formula_id),
            "confirmed_at": datetime.now(UTC).isoformat(),
        }
        state["confirmed_formulas"][formula_id] = entry
        write_json_atomic(self.path, state)
        return entry

    def is_confirmed(self, final: dict[str, Any], formula_id: str) -> bool:
        entry = self._load()["confirmed_formulas"].get(formula_id)
        if not isinstance(entry, dict):
            return False
        try:
            return entry.get("content_hash") == formula_content_hash(final, formula_id)
        except ReviewInputError:
            return False

    def confirmation_map(self, final: dict[str, Any]) -> dict[str, bool]:
        return {
            formula_id: self.is_confirmed(final, formula_id)
            for formula_id in self._load()["confirmed_formulas"]
        }

    def confirmed_hashes(self, final: dict[str, Any]) -> dict[str, str]:
        state = self._load()
        return {
            formula_id: str(entry["content_hash"])
            for formula_id, entry in state["confirmed_formulas"].items()
            if isinstance(entry, dict) and self.is_confirmed(final, formula_id)
        }

    def _load(self) -> dict[str, Any]:
        state = read_json_optional(self.path)
        if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA_VERSION:
            return {"schema_version": STATE_SCHEMA_VERSION, "confirmed_formulas": {}}
        if not isinstance(state.get("confirmed_formulas"), dict):
            state["confirmed_formulas"] = {}
        return state


def formula_content_hash(final: dict[str, Any], formula_id: str) -> str:
    page, section, formula = find_identity_and_formula(final, formula_id)
    company = page.get("company", {})
    product = section.get("product_or_series", {})
    payload = {
        "customer": company.get("standard_value") or company.get("raw_value") or "",
        "product": product.get("value", ""),
        "formula": formula,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def confirm_formula(
    editor: ReviewEditor,
    store: ReviewStateStore,
    formula_id: str,
    expected_version: str,
) -> dict[str, Any]:
    final = editor.load()
    page, section, formula = find_identity_and_formula(final, formula_id)
    _validate_business_requirements(page, section, formula)

    def mark_confirmed(current: dict[str, Any]) -> None:
        current_page, current_section, current_formula = find_identity_and_formula(
            current, formula_id
        )
        company = current_page["company"]
        company["review_status"] = "MANUAL_CONFIRMED"
        company["confidence"] = 1.0
        company["match_source"] = "manual"
        _mark_field(current_section["product_or_series"])
        for field in _formula_fields(current_formula):
            _mark_field(field)

    editor._mutate(expected_version, "confirm_formula", mark_confirmed)
    final = editor.load()
    entry = store.confirm(final, formula_id)
    return {
        "confirmed": True,
        "formula_id": formula_id,
        "content_hash": entry["content_hash"],
        "version": final["updated_at"],
    }


def _validate_business_requirements(
    page: dict[str, Any], section: dict[str, Any], formula: dict[str, Any]
) -> None:
    company = page.get("company", {})
    customer = company.get("standard_value") or company.get("raw_value")
    if not str(customer or "").strip():
        raise ReviewInputError("请先填写客户名称")
    if not str(section.get("product_or_series", {}).get("value", "")).strip():
        raise ReviewInputError("请先填写产品名称")
    materials = formula.get("materials", [])
    if not materials:
        raise ReviewInputError("请至少添加一项材料")
    for index, material in enumerate(materials, 1):
        if not str(material.get("name", {}).get("value", "")).strip():
            raise ReviewInputError(f"第 {index} 项材料名称不能为空")
        if not str(material.get("amount", {}).get("value", "")).strip():
            raise ReviewInputError(f"第 {index} 项材料数量不能为空")
    for index, parameter in enumerate(formula.get("process_parameters", []), 1):
        if not str(parameter.get("name", {}).get("value", "")).strip():
            raise ReviewInputError(f"第 {index} 项工艺名称不能为空")
        if not str(parameter.get("value", {}).get("value", "")).strip():
            raise ReviewInputError(f"第 {index} 项工艺内容不能为空")


def _formula_fields(formula: dict[str, Any]):
    yield formula["record_date"]
    yield formula["notes"]
    for material in formula.get("materials", []):
        yield material["name"]
        yield material["amount"]
        yield material["unit"]
    for parameter in formula.get("process_parameters", []):
        yield parameter["name"]
        yield parameter["value"]
        yield parameter["unit"]


def _mark_field(field: dict[str, Any]) -> None:
    value = str(field.get("value", ""))
    status = "MANUAL_CONFIRMED" if value.strip() else "MANUAL_CONFIRMED_EMPTY"
    field.update(
        {
            "status": status,
            "review_status": status,
            "confidence": 1.0,
            "source": "manual",
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
