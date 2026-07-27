"""Read-only, evidence-first presentation of a canonical FinalResult."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .date_values import parse_record_date

REVIEW_STATUSES = {"CONFLICT", "EMPTY", "NEED_REVIEW"}


def present_field(field: dict[str, Any], *, required: bool) -> dict[str, Any]:
    """Return only the business-facing state needed by the review UI."""
    value = str(field.get("value", ""))
    status = str(field.get("status", field.get("review_status", "NEED_REVIEW")))
    return {
        "id": str(field.get("field_id", "")),
        "value": value,
        "needs_confirmation": status in REVIEW_STATUSES or (required and not value.strip()),
        "confidence": float(field.get("confidence", 0.0)),
    }


def build_review_view(
    job: dict[str, Any],
    final: dict[str, Any],
    confirmed: dict[str, Any] | None = None,
    *,
    evidence_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Group formulas into customer/product cards with evidence and issue state."""
    confirmed = confirmed or {}
    evidence_urls = evidence_urls or {}
    groups: list[dict[str, Any]] = []
    issue_count = 0
    confirmed_count = 0
    formula_count = 0

    for page in final.get("pages", []):
        customer = _company_name(page.get("company", {}))
        image_index = int(page.get("source_image_index", 1))
        image_url = _image_url(job, image_index)
        for section in page.get("product_sections", []):
            product_field = section.get("product_or_series", {})
            product = str(product_field.get("value", ""))
            formulas = [
                _present_formula(
                    formula,
                    customer=customer,
                    product=product,
                    image_url=image_url,
                    crop_url=evidence_urls.get(str(formula.get("formula_id", "")), ""),
                    confirmed=bool(confirmed.get(str(formula.get("formula_id", "")), False)),
                )
                for formula in section.get("formulas", [])
            ]
            formulas.sort(key=lambda item: (not item["needs_confirmation"], item["sequence"]))
            formula_count += len(formulas)
            issue_count += sum(bool(item["needs_confirmation"]) for item in formulas)
            confirmed_count += sum(bool(item["confirmed"]) for item in formulas)
            groups.append(
                {
                    "id": str(section.get("section_id", "")),
                    "customer": customer,
                    "product": product,
                    "formulas": formulas,
                }
            )

    groups.sort(
        key=lambda group: not any(
            formula["needs_confirmation"] for formula in group["formulas"]
        )
    )
    return {
        "summary": {
            "total_formulas": formula_count,
            "needs_confirmation": issue_count,
            "confirmed": confirmed_count,
        },
        "groups": groups,
        "advanced": {
            "job_id": str(job.get("id", final.get("job_id", ""))),
            "job_status": str(job.get("status", "")),
            "schema_version": str(final.get("schema_version", "")),
        },
    }


def _present_formula(
    formula: dict[str, Any],
    *,
    customer: str,
    product: str,
    image_url: str,
    crop_url: str,
    confirmed: bool,
) -> dict[str, Any]:
    formula_id = str(formula.get("formula_id", ""))
    formula_no = str(formula.get("formula_no", "")) or "未编号配方"
    date = present_field(formula.get("record_date", {}), required=False)
    parsed_date = parse_record_date(date["value"])
    date["sort_value"] = parsed_date.sort_value
    date["parse_status"] = parsed_date.status
    date_pending = not date["value"].strip()
    if date_pending:
        date["needs_confirmation"] = False
    notes = present_field(formula.get("notes", {}), required=False)
    materials = [_present_material(item) for item in formula.get("materials", [])]
    process = [_present_process(item) for item in formula.get("process_parameters", [])]
    field_issue = (
        date["needs_confirmation"]
        or any(
            item["name"]["needs_confirmation"] or item["amount"]["needs_confirmation"]
            for item in materials
        )
        or any(
            item["name"]["needs_confirmation"] or item["value"]["needs_confirmation"]
            for item in process
        )
    )
    needs_confirmation = bool(field_issue and not confirmed)
    return {
        "id": formula_id,
        "formula_no": formula_no,
        "sequence": int(formula.get("formula_sequence", 0)),
        "date": date,
        "date_pending": date_pending,
        "materials": materials,
        "process": process,
        "notes": notes,
        "needs_confirmation": needs_confirmation,
        "confirmed": confirmed,
        "collapsed": not needs_confirmation,
        "blocking_message": _blocking_message(
            customer,
            product,
            formula_no,
            date=date,
            materials=materials,
            process=process,
        ),
        "evidence": {
            "image_url": crop_url or image_url,
            "full_image_url": image_url,
            "rect": None if crop_url else _normalized_rect(formula.get("record_bbox")),
        },
        "labels": {
            "date": "日期",
            "materials": "材料与数量",
            "process": "工艺",
            "notes": "备注",
        },
    }


def _present_material(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(material.get("material_id", "")),
        "name": present_field(material.get("name", {}), required=True),
        "amount": present_field(material.get("amount", {}), required=True),
        "unit": present_field(material.get("unit", {}), required=False),
    }


def _present_process(parameter: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(parameter.get("parameter_id", "")),
        "name": present_field(parameter.get("name", {}), required=True),
        "value": present_field(parameter.get("value", {}), required=True),
        "unit": present_field(parameter.get("unit", {}), required=False),
    }


def _company_name(company: dict[str, Any]) -> str:
    return str(
        company.get("standard_value")
        or company.get("raw_value")
        or company.get("value")
        or "未填写客户"
    )


def _image_url(job: dict[str, Any], image_index: int) -> str:
    images = job.get("images", [])
    if image_index < 1 or image_index > len(images):
        return ""
    source = str(images[image_index - 1].get("source", ""))
    if not source:
        return ""
    job_id = quote(str(job.get("id", "")), safe="")
    return f"/jobs/{job_id}/files/{quote(source, safe='/')}"


def _normalized_rect(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        return [min(1.0, max(0.0, float(coordinate))) for coordinate in value]
    except (TypeError, ValueError):
        return None


def _blocking_message(
    customer: str,
    product: str,
    formula_no: str,
    *,
    date: dict[str, Any],
    materials: list[dict[str, Any]],
    process: list[dict[str, Any]],
) -> str:
    prefix = f"待确认：{customer} / {product} / {formula_no}"
    if date["needs_confirmation"]:
        return f"{prefix} 日期需要确认"
    if any(item["name"]["needs_confirmation"] for item in materials):
        return f"{prefix} 材料名称需要确认"
    if any(item["amount"]["needs_confirmation"] for item in materials):
        return f"{prefix} 材料数量需要确认"
    if any(
        item["name"]["needs_confirmation"] or item["value"]["needs_confirmation"]
        for item in process
    ):
        return f"{prefix} 工艺需要确认"
    return ""
