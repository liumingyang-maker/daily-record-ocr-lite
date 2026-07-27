"""Single fail-closed READY gate for pipeline, review, confirmation, and export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .contracts import (
    ValidationIssue,
    ValidationReport,
    validate_page_coverage,
    validate_record_result,
)
from .grouping.service import final_result_fingerprint
from .grouping.storage import load_business_entities
from .storage import read_json_optional

_RESOLVED_STATUSES = {
    "AUTO_ACCEPT",
    "MANUAL_CONFIRMED",
    "MANUAL_CONFIRMED_EMPTY",
}
_FINAL_FIELD_KEYS = {
    "field_id",
    "value",
    "status",
    "confidence",
    "source",
    "candidates",
    "bbox",
    "source_image_index",
    "updated_at",
}


@dataclass(frozen=True)
class ReadyGateResult:
    ready: bool
    unresolved_fields: list[str]
    reasons: list[str]
    validation: ValidationReport


def iter_final_fields(final: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for page in final.get("pages", []):
        for section in page.get("product_sections", []):
            product = section.get("product_or_series")
            if isinstance(product, dict):
                yield str(product.get("field_id", "product_or_series")), product
            for formula in section.get("formulas", []):
                for name in ("record_date", "notes"):
                    field = formula.get(name)
                    if isinstance(field, dict):
                        yield str(field.get("field_id", name)), field
                for material in formula.get("materials", []):
                    for name in ("name", "amount", "unit"):
                        field = material.get(name)
                        if isinstance(field, dict):
                            yield str(field.get("field_id", name)), field
                for parameter in formula.get("process_parameters", []):
                    for name in ("name", "value", "unit"):
                        field = parameter.get(name)
                        if isinstance(field, dict):
                            yield str(field.get("field_id", name)), field


def validate_final_result_contract(final: Any) -> ValidationReport:
    """Validate record-v1 plus the metadata required of canonical FinalResult."""
    report = validate_record_result(final)
    if not isinstance(final, dict):
        return report
    for key in ("job_id", "updated_at", "summary"):
        if key not in final:
            report.fatal.append(
                ValidationIssue(
                    json_path=f"$.{key}",
                    message=f"FinalResult 缺少 {key}",
                    validator="finalResultRequired",
                    severity="fatal",
                )
            )
    for field_id, field in iter_final_fields(final):
        missing = sorted(_FINAL_FIELD_KEYS.difference(field))
        if missing:
            report.fatal.append(
                ValidationIssue(
                    json_path=f"$.fields[{field_id}]",
                    message=f"FinalResult 字段缺少元数据: {', '.join(missing)}",
                    validator="finalResultRequired",
                    severity="fatal",
                )
            )
    return report


def collect_unresolved_fields(final: dict[str, Any]) -> list[str]:
    unresolved: list[str] = []
    for page in final.get("pages", []):
        company = page.get("company")
        if isinstance(company, dict):
            company_status = str(company.get("review_status", ""))
            if company_status not in _RESOLVED_STATUSES:
                unresolved.append(f"{page.get('page_id', 'page')}__company")
        else:
            unresolved.append(f"{page.get('page_id', 'page')}__company")
    for field_id, field in iter_final_fields(final):
        if str(field.get("status", "")) not in _RESOLVED_STATUSES:
            unresolved.append(field_id)
    return unresolved


def evaluate_content_gate(
    job: dict[str, Any],
    final: dict[str, Any],
    job_dir: Path,
) -> ReadyGateResult:
    """Check recognized content and projections before knowledge finalization."""
    validation = validate_final_result_contract(final)
    validation.fatal.extend(
        validate_page_coverage(final, expected_pages=len(job.get("images", [])))
    )
    unresolved = collect_unresolved_fields(final)
    reasons: list[str] = []
    if validation.issues:
        reasons.append(f"FinalResult 合同错误 {len(validation.issues)} 项")
    if unresolved:
        reasons.append(f"未解决字段 {len(unresolved)} 项")
    if job.get("demo_mode"):
        reasons.append("演示模式不能 READY")

    ocr = job.get("ocr_engine")
    _ocr_provider = str(
        (ocr or {}).get("effective_provider", "") or (ocr or {}).get("configured_provider", "")
    ).lower()
    if not isinstance(ocr, dict) or "paddleocr" not in _ocr_provider or not bool(ocr.get("loaded")):
        reasons.append("真实 OCR Provider 未验证可用")

    vision = job.get("vision_engine")
    if not isinstance(vision, dict) or (
        vision.get("provider") != "openai_compatible"
        or not vision.get("model")
        or not bool(vision.get("healthy"))
    ):
        reasons.append("真实 Vision Provider 未验证可用")

    if final.get("job_id") != job.get("id"):
        reasons.append("FinalResult 与 Job 不匹配")
    run_id = job.get("recognition_run_id")
    if not run_id or final.get("recognition_run_id") != run_id:
        reasons.append("FinalResult 不属于当前识别运行")

    try:
        entities = load_business_entities(job_dir)
    except Exception:
        entities = None
    if entities is None:
        reasons.append("BusinessEntities 投影缺失或损坏")
    else:
        expected_pages = [
            (
                str(page.get("page_id", "")),
                int(page.get("source_image_index", 0)),
            )
            for page in final.get("pages", [])
        ]
        projected_pages = [(page.page_id, page.source_image_index) for page in entities.pages]
        expected_formulas = [
            str(formula.get("formula_id", ""))
            for page in final.get("pages", [])
            for section in page.get("product_sections", [])
            for formula in section.get("formulas", [])
        ]
        projected_formulas = [formula.formula_id for formula in entities.formulas]
        if (
            entities.schema_version != "business-entities-v1"
            or entities.job_id != job.get("id")
            or entities.recognition_run_id != run_id
            or entities.final_result_sha256 != final_result_fingerprint(final)
            or projected_pages != expected_pages
            or projected_formulas != expected_formulas
        ):
            reasons.append("BusinessEntities 投影与当前 FinalResult 不一致")

    return ReadyGateResult(
        ready=not reasons,
        unresolved_fields=unresolved,
        reasons=reasons,
        validation=validation,
    )


def evaluate_ready_gate(
    job: dict[str, Any],
    final: dict[str, Any],
    job_dir: Path,
) -> ReadyGateResult:
    """Require content readiness plus a receipt bound to this exact FinalResult."""
    content = evaluate_content_gate(job, final, job_dir)
    reasons = list(content.reasons)
    receipt = read_json_optional(job_dir / "review" / "finalization.json")
    if not isinstance(receipt, dict) or receipt.get(
        "final_result_sha256"
    ) != final_result_fingerprint(final):
        reasons.append("最终确认回执缺失或已失效")
    return ReadyGateResult(
        ready=not reasons,
        unresolved_fields=content.unresolved_fields,
        reasons=reasons,
        validation=content.validation,
    )
