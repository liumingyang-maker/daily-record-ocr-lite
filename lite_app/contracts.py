"""Versioned recognition contracts and strict Draft 2020-12 validation."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from .config import PROJECT_ROOT


@dataclass(frozen=True)
class ValidationIssue:
    json_path: str
    message: str
    validator: str
    severity: str

    def to_dict(self) -> dict[str, str]:
        return {
            "json_path": self.json_path,
            "message": self.message,
            "validator": self.validator,
            "severity": self.severity,
        }


@dataclass
class ValidationReport:
    fatal: list[ValidationIssue] = field(default_factory=list)
    reviewable: list[ValidationIssue] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.fatal and not self.reviewable

    @property
    def issues(self) -> list[ValidationIssue]:
        return [*self.fatal, *self.reviewable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fatal": [issue.to_dict() for issue in self.fatal],
            "reviewable": [issue.to_dict() for issue in self.reviewable],
            "ready": self.ready,
        }


def load_schema_file(name: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "config" / "schema" / name
    with path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def load_record_schema() -> dict[str, Any]:
    return load_schema_file("record-v1.schema.json")


def _severity(error: Any) -> str:
    path = tuple(str(item) for item in error.absolute_path)
    if error.validator == "required":
        missing_metadata = {"bbox", "evidence_token_ids", "confidence"}
        if any(f"'{name}' is a required property" in error.message for name in missing_metadata):
            return "reviewable"
        return "fatal"
    if error.validator in {"type", "additionalProperties", "const"}:
        return "fatal"
    if "source_image_index" in path or "materials" in path or "pages" in path:
        return "fatal"
    return "reviewable"


def validate_record_result(result: Any) -> ValidationReport:
    report = ValidationReport()
    validator = Draft202012Validator(load_record_schema())
    for error in sorted(validator.iter_errors(result), key=lambda item: list(item.path)):
        path = "$"
        for item in error.absolute_path:
            path += f"[{item}]" if isinstance(item, int) else f".{item}"
        issue = ValidationIssue(
            json_path=path,
            message=error.message,
            validator=str(error.validator),
            severity=_severity(error),
        )
        if issue.severity == "fatal":
            report.fatal.append(issue)
        else:
            report.reviewable.append(issue)
    return report


def validate_page_coverage(
    result: dict[str, Any],
    expected_pages: int,
) -> list[ValidationIssue]:
    """Require one unique, ordered page for every uploaded source image."""
    pages = result.get("pages")
    indexes = (
        [page.get("source_image_index") for page in pages if isinstance(page, dict)]
        if isinstance(pages, list)
        else []
    )
    expected = list(range(1, expected_pages + 1))
    if indexes == expected:
        return []
    return [
        ValidationIssue(
            json_path="$.pages",
            message=(
                f"页面覆盖不完整：上传 {expected_pages} 张，"
                f"source_image_index={indexes!r}，期望 {expected!r}"
            ),
            validator="pageCoverage",
            severity="fatal",
        )
    ]


def normalize_legacy_result(result: dict[str, Any], job_id: str = "legacy") -> dict[str, Any]:
    """Convert the pre-v1 records contract without mutating the source object."""
    # Already in pages format (with or without schema_version)
    if isinstance(result.get("pages"), list):
        normalized = copy.deepcopy(result)
        if not normalized.get("schema_version"):
            normalized["schema_version"] = "record-v1"
        if not isinstance(normalized.get("warnings"), list):
            normalized["warnings"] = []
        _assign_stable_ids(normalized, job_id)
        _fill_reviewable_metadata(normalized)
        return normalized

    records = result.get("records")
    if not isinstance(records, list):
        return copy.deepcopy(result)

    pages: dict[int, dict[str, Any]] = {}
    for sequence, record in enumerate(records, 1):
        indexes = record.get("source_image_indexes") or [1]
        image_index = int(indexes[0])
        page = pages.setdefault(
            image_index,
            {
                "page_id": f"page_{image_index:03d}",
                "source_image_index": image_index,
                "company": {
                    "raw_value": str(result.get("page_heading", "")),
                    "standard_value": str(result.get("page_heading", "")),
                    "confidence": 0.0,
                    "bbox": None,
                    "evidence_token_ids": [],
                    "match_source": "legacy",
                    "review_status": "NEED_REVIEW",
                },
                "product_sections": [
                    {
                        "section_id": f"page_{image_index:03d}__section_001",
                        "product_or_series": _legacy_field(""),
                        "product_type": "unknown",
                        "section_bbox": None,
                        "formulas": [],
                        "warnings": [],
                    }
                ],
                "warnings": [],
            },
        )
        formula_id = f"{job_id}__page_{image_index:03d}__formula_{sequence:03d}"
        materials = []
        for index, material in enumerate(record.get("materials", []), 1):
            materials.append(
                {
                    "material_id": f"material_{index:03d}",
                    "name": _legacy_field(material.get("name", "")),
                    "amount": _legacy_field(material.get("amount", "")),
                    "unit": _legacy_field(material.get("unit", "")),
                    "warnings": [],
                }
            )
        parameters = []
        for index, parameter in enumerate(record.get("process_parameters", []), 1):
            parameters.append(
                {
                    "parameter_id": f"parameter_{index:03d}",
                    "name": _legacy_field(parameter.get("name", "")),
                    "value": _legacy_field(parameter.get("value", "")),
                    "unit": _legacy_field(parameter.get("unit", "")),
                    "warnings": [],
                }
            )
        page["product_sections"][0]["formulas"].append(
            {
                "formula_id": formula_id,
                "formula_no": str(record.get("formula_no", "")),
                "formula_sequence": sequence,
                "record_date": _legacy_field(record.get("record_date", "")),
                "record_bbox": record.get("record_bbox"),
                "materials": materials,
                "process_parameters": parameters,
                "notes": _legacy_field(record.get("notes", "")),
                "warnings": list(record.get("warnings", [])),
                "confidence": float(record.get("confidence", 0.0)),
            }
        )
    normalized = {
        "schema_version": "record-v1",
        "pages": [pages[index] for index in sorted(pages)],
        "warnings": list(result.get("warnings", [])),
    }
    _assign_stable_ids(normalized, job_id)
    _fill_reviewable_metadata(normalized)
    return normalized


def _assign_stable_ids(result: dict[str, Any], job_id: str) -> None:
    """Replace model-provided identifiers with deterministic local identifiers."""
    for page_position, page in enumerate(result.get("pages", []), 1):
        image_index = int(page.get("source_image_index", page_position))
        page_id = f"page_{image_index:03d}"
        page["page_id"] = page_id
        formula_position = 0
        for section_position, section in enumerate(page.get("product_sections", []), 1):
            section["section_id"] = f"{page_id}__section_{section_position:03d}"
            for formula in section.get("formulas", []):
                formula_position += 1
                formula["formula_id"] = f"{job_id}__{page_id}__formula_{formula_position:03d}"
                formula["formula_sequence"] = formula_position
                for material_position, material in enumerate(formula.get("materials", []), 1):
                    material["material_id"] = f"material_{material_position:03d}"
                for parameter_position, parameter in enumerate(
                    formula.get("process_parameters", []), 1
                ):
                    parameter["parameter_id"] = f"parameter_{parameter_position:03d}"


def _fill_reviewable_metadata(result: dict[str, Any]) -> None:
    """Fill recoverable evidence metadata while forcing affected fields to review."""

    _VALID_REVIEW = {"AUTO_ACCEPT", "NEED_REVIEW", "MANUAL_CONFIRMED", "MANUAL_REJECTED", "MANUAL_CONFIRMED_EMPTY"}

    def _sanitize_bbox(bbox: Any) -> Any:
        """bbox must be null or [0-1] normalized 4-element array."""
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return None
        if all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in bbox):
            return list(bbox)
        return None  # pixel coordinates or invalid → null

    def fill(field: Any) -> None:
        if not isinstance(field, dict):
            return
        missing = [key for key in ("confidence", "evidence_token_ids", "bbox") if key not in field]
        field.setdefault("confidence", 0.0)
        field.setdefault("evidence_token_ids", [])
        field.setdefault("bbox", None)
        # Sanitize bbox (pixel coords → null)
        field["bbox"] = _sanitize_bbox(field.get("bbox"))
        # Fix invalid review_status
        rs = field.get("review_status", "")
        if rs not in _VALID_REVIEW:
            # If missing evidence fields, mark as NEED_REVIEW; otherwise AUTO_ACCEPT
            if missing:
                field["review_status"] = "NEED_REVIEW"
            else:
                field["review_status"] = "AUTO_ACCEPT"
        else:
            # Valid review_status exists; if missing evidence, override to NEED_REVIEW
            if missing:
                field["review_status"] = "NEED_REVIEW"

    def ensure_field(parent: dict, key: str) -> dict:
        """Ensure a field dict exists with default structure."""
        val = parent.get(key)
        if isinstance(val, list):
            # Model sometimes returns array; take first element or empty
            val = val[0] if val and isinstance(val[0], dict) else {}
        if not isinstance(val, dict):
            val = {"value": str(val or ""), "confidence": 0.0, "evidence_token_ids": [], "bbox": None}
            parent[key] = val
        # Remove 'unit' if nested inside an evidenceField (not allowed by schema)
        val.pop("unit", None)
        fill(val)
        return val

    for page in result.get("pages", []):
        # Fix source_image_index (model may return 0-based)
        idx = page.get("source_image_index", 1)
        if isinstance(idx, int) and idx < 1:
            page["source_image_index"] = idx + 1
        # Company
        company = page.get("company")
        if isinstance(company, dict):
            fill(company)
        # Product sections
        for section in page.get("product_sections", []):
            # Ensure required section fields
            if "product_or_series" not in section:
                section["product_or_series"] = {"value": "", "confidence": 0.0, "evidence_token_ids": [], "bbox": None}
            fill(section.get("product_or_series"))
            section.setdefault("product_type", "unknown")
            section.setdefault("section_bbox", None)
            section.setdefault("section_id", "")
            section.setdefault("warnings", [])
            for formula in section.get("formulas", []):
                # Ensure formula required fields
                if "formula_no" not in formula:
                    formula["formula_no"] = ""
                if "record_date" not in formula:
                    formula["record_date"] = {"value": "", "confidence": 0.0, "evidence_token_ids": [], "bbox": None}
                fill(formula.get("record_date"))
                if "notes" not in formula:
                    formula["notes"] = {"value": "", "confidence": 0.0, "evidence_token_ids": [], "bbox": None}
                # notes might be array from model → convert to single evidenceField
                if isinstance(formula.get("notes"), list):
                    notes_list = formula["notes"]
                    if notes_list and isinstance(notes_list[0], dict):
                        formula["notes"] = notes_list[0]
                    else:
                        formula["notes"] = {"value": "", "confidence": 0.0, "evidence_token_ids": [], "bbox": None}
                fill(formula.get("notes"))
                formula.setdefault("formula_id", "")
                formula.setdefault("formula_sequence", 0)
                formula["record_bbox"] = _sanitize_bbox(formula.get("record_bbox"))
                formula.setdefault("warnings", [])
                formula.setdefault("confidence", 0.0)
                for material in formula.get("materials", []):
                    ensure_field(material, "name")
                    ensure_field(material, "amount")
                    ensure_field(material, "unit")
                    # material_id is already assigned by _assign_stable_ids
                    material.setdefault("warnings", [])
                    # Remove fields not allowed by schema (additionalProperties: false)
                    material.pop("review_status", None)
                    material.pop("confidence", None)
                    material.pop("evidence_token_ids", None)
                    material.pop("bbox", None)
                for parameter in formula.get("process_parameters", []):
                    ensure_field(parameter, "name")
                    ensure_field(parameter, "value")
                    ensure_field(parameter, "unit")
                    # parameter_id is already assigned by _assign_stable_ids
                    parameter.setdefault("warnings", [])
                    parameter.pop("review_status", None)
                    parameter.pop("confidence", None)
                    parameter.pop("evidence_token_ids", None)
                    parameter.pop("bbox", None)


def _legacy_field(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "value": str(value.get("value", value.get("raw_value", ""))),
            "confidence": float(value.get("confidence", 0.0)),
            "evidence_token_ids": list(value.get("evidence_token_ids", [])),
            "bbox": value.get("bbox"),
        }
    return {
        "value": str(value or ""),
        "confidence": 0.0,
        "evidence_token_ids": [],
        "bbox": None,
    }
