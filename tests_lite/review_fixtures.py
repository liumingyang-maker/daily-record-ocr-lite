"""Synthetic fixtures for the evidence-first review workflow."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from lite_app.final_result import project_final_result

ROOT = Path(__file__).resolve().parents[1]


def make_review_final(job_id: str) -> dict[str, Any]:
    """Build a strict FinalResult without reading private job data."""
    structured = json.loads((ROOT / "config" / "mock_result.json").read_text("utf-8"))
    structured = copy.deepcopy(structured)
    page = structured["pages"][0]
    page["company"]["raw_value"] = "联创"
    page["company"]["standard_value"] = "联创"
    page["company"]["review_status"] = "AUTO_ACCEPT"
    section = page["product_sections"][0]
    section["product_or_series"]["value"] = "G30A"
    formula = section["formulas"][0]
    formula["formula_id"] = f"{job_id}__page_001__formula_001"
    formula["formula_no"] = "配方1"

    final = project_final_result(job_id, structured, {"fields": []})
    formula = final["pages"][0]["product_sections"][0]["formulas"][0]
    formula["record_date"]["value"] = ""
    formula["record_date"]["status"] = "EMPTY"
    formula["record_date"]["review_status"] = "EMPTY"
    formula["materials"][0]["amount"]["status"] = "CONFLICT"
    formula["materials"][0]["amount"]["review_status"] = "CONFLICT"

    for field in (
        final["pages"][0]["product_sections"][0]["product_or_series"],
        formula["materials"][0]["name"],
    ):
        field["status"] = "AUTO_ACCEPT"
        field["review_status"] = "AUTO_ACCEPT"
    return final
