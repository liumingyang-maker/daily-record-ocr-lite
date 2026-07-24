"""Canonical nested FinalResult and synchronized human review updates."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage import (
    read_json_optional,
    read_json_required,
    write_json_atomic,
)


class FinalResultError(RuntimeError):
    """FinalResult is missing, malformed, or cannot be synchronized."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def project_final_result(
    job_id: str,
    structured_result: dict[str, Any],
    fusion_result: dict[str, Any],
) -> dict[str, Any]:
    final = copy.deepcopy(structured_result)
    final["schema_version"] = "record-v1"
    final["job_id"] = job_id
    final["updated_at"] = _now()
    fused = {
        field["field_id"]: field
        for field in fusion_result.get("fields", [])
        if field.get("field_id")
    }
    for page in final.get("pages", []):
        company = page.get("company")
        if isinstance(company, dict):
            missing = any(
                key not in company for key in ("confidence", "evidence_token_ids", "bbox")
            )
            company.setdefault("confidence", 0.0)
            company.setdefault("evidence_token_ids", [])
            company.setdefault("bbox", None)
            if missing or (
                company.get("review_status") == "AUTO_ACCEPT"
                and not company.get("evidence_token_ids")
            ):
                company["review_status"] = "NEED_REVIEW"

    for field_id, field, source_image_index, record_bbox in _iter_fields(final):
        current = field.get("value", "")
        match = fused.get(field_id)
        missing = any(key not in field for key in ("confidence", "evidence_token_ids", "bbox"))
        field.setdefault("confidence", 0.0)
        field.setdefault("evidence_token_ids", [])
        field.setdefault("bbox", None)
        if missing:
            field["review_status"] = "NEED_REVIEW"
        field["field_id"] = field_id
        field["value"] = match.get("final_value", current) if match else current
        default_status = (
            "AUTO_ACCEPT" if float(field.get("confidence", 0.0)) >= 0.9 else "NEED_REVIEW"
        )
        structured_status = field.get("status") or field.get("review_status")
        status = (
            match.get("status", default_status) if match else structured_status or default_status
        )
        candidate_evidence = any(
            candidate.get("evidence")
            for candidate in (match or {}).get("candidates", [])
            if isinstance(candidate, dict)
        )
        if (
            status == "AUTO_ACCEPT"
            and not field.get("evidence_token_ids")
            and not candidate_evidence
        ):
            status = "NEED_REVIEW"
        field["status"] = status
        field["review_status"] = field["status"]
        field["confidence"] = float(
            match.get("final_confidence", field.get("confidence", 0.0))
            if match
            else field.get("confidence", 0.0)
        )
        field["source"] = match.get("final_source", "vlm") if match else "vlm"
        field["candidates"] = copy.deepcopy(match.get("candidates", [])) if match else []
        field["bbox"] = match.get("bbox", field.get("bbox")) if match else field.get("bbox")
        field["source_image_index"] = source_image_index
        field["record_bbox"] = record_bbox
        field["recheck_count"] = int(field.get("recheck_count", 0))
        field["updated_at"] = final["updated_at"]

    final["summary"] = summarize_final_result(final)
    return final


def summarize_final_result(final: dict[str, Any]) -> dict[str, int]:
    statuses: dict[str, int] = {}
    total = 0
    for _, field, _, _ in _iter_fields(final):
        total += 1
        status = str(field.get("status", "NEED_REVIEW"))
        statuses[status] = statuses.get(status, 0) + 1
    return {"total_fields": total, **{key.lower(): value for key, value in statuses.items()}}


class FinalResultService:
    def __init__(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.path = job_dir / "review" / "final_result.json"

    def save(self, final: dict[str, Any]) -> None:
        from .readiness import validate_final_result_contract

        report = validate_final_result_contract(final)
        if report.issues:
            raise FinalResultError(
                f"FinalResult 合同无效: {report.issues[0].json_path} {report.issues[0].message}"
            )
        write_json_atomic(self.path, final)
        write_json_atomic(self.job_dir / "result.json", final)

    def load(self) -> dict[str, Any]:
        try:
            data = read_json_required(self.path)
        except Exception as exc:
            raise FinalResultError(str(exc)) from exc
        if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
            raise FinalResultError("FinalResult 必须包含 pages[]")
        from .readiness import validate_final_result_contract

        report = validate_final_result_contract(data)
        if report.issues:
            raise FinalResultError(
                f"FinalResult 合同无效: {report.issues[0].json_path} {report.issues[0].message}"
            )
        return data

    def update_field(
        self,
        field_id: str,
        value: str,
        source: str = "manual",
    ) -> dict[str, Any]:
        final = self.load()
        target = None
        for candidate_id, field, _, _ in _iter_fields(final):
            if candidate_id == field_id or field.get("field_id") == field_id:
                target = field
                break
        if target is None:
            raise FinalResultError(f"字段不存在: {field_id}")
        old_value = str(target.get("value", ""))
        target["value"] = str(value)
        target["source"] = source
        target["status"] = "MANUAL_CONFIRMED" if str(value) else "MANUAL_CONFIRMED_EMPTY"
        target["review_status"] = target["status"]
        target["confidence"] = 1.0
        target["updated_at"] = _now()
        final["updated_at"] = target["updated_at"]
        final["summary"] = summarize_final_result(final)
        self.save(final)
        self._sync_fusion(field_id, target)
        self._append_correction(field_id, old_value, str(value), source)
        self._project_business_entities(final)
        return target

    def choose_candidate(self, field_id: str, source: str) -> dict[str, Any]:
        final = self.load()
        target = next(
            (
                field
                for candidate_id, field, _, _ in _iter_fields(final)
                if candidate_id == field_id or field.get("field_id") == field_id
            ),
            None,
        )
        if target is None:
            raise FinalResultError(f"字段不存在: {field_id}")

        def source_matches(candidate_source: str) -> bool:
            if source == "ocr":
                return candidate_source.startswith(("ocr", "local_ocr"))
            if source == "vlm":
                return candidate_source == "vlm" or candidate_source.startswith("local_vlm")
            return candidate_source == source

        candidate = next(
            (
                item
                for item in target.get("candidates", [])
                if source_matches(str(item.get("source", "")))
            ),
            None,
        )
        if candidate is None:
            raise FinalResultError(f"字段 {field_id} 没有来源 {source} 的候选值")
        return self.update_field(field_id, str(candidate.get("value", "")), source)

    def replace(self, final: dict[str, Any]) -> None:
        final["updated_at"] = _now()
        final["summary"] = summarize_final_result(final)
        self.save(final)
        self._project_business_entities(final)

    def _sync_fusion(self, field_id: str, field: dict[str, Any]) -> None:
        path = self.job_dir / "fusion" / "result.json"
        fusion = read_json_optional(path)
        if not isinstance(fusion, dict):
            return
        for item in fusion.get("fields", []):
            if item.get("field_id") == field_id:
                item["final_value"] = field["value"]
                item["final_source"] = field["source"]
                item["final_confidence"] = field["confidence"]
                item["status"] = field["status"]
                break
        write_json_atomic(path, fusion)

    def _append_correction(
        self,
        field_id: str,
        old_value: str,
        new_value: str,
        source: str,
    ) -> None:
        path = self.job_dir / "review" / "corrections.json"
        corrections = read_json_optional(path)
        if not isinstance(corrections, list):
            corrections = []
        corrections.append(
            {
                "field_id": field_id,
                "old_value": old_value,
                "new_value": new_value,
                "chosen_source": source,
                "updated_at": _now(),
            }
        )
        write_json_atomic(path, corrections)

    def _project_business_entities(self, final: dict[str, Any]) -> None:
        from .grouping.review import build_reviewed_business_entities
        from .grouping.storage import save_business_entities

        entities = build_reviewed_business_entities(
            self.job_dir,
            str(final.get("job_id", "job")),
            final,
        )
        save_business_entities(self.job_dir, entities)


def _iter_fields(
    final: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any], int, list[float] | None]]:
    for page in final.get("pages", []):
        image_index = int(page.get("source_image_index", 1))
        for section_index, section in enumerate(page.get("product_sections", []), 1):
            product = section.get("product_or_series")
            if isinstance(product, dict):
                section_id = section.get("section_id", f"section_{section_index:03d}")
                yield (
                    f"{page.get('page_id', 'page')}__{section_id}__product",
                    product,
                    image_index,
                    section.get("section_bbox"),
                )
            for formula_index, formula in enumerate(section.get("formulas", []), 1):
                formula_id = formula.get(
                    "formula_id",
                    f"{final.get('job_id', 'job')}__page_{image_index:03d}__formula_{formula_index:03d}",
                )
                for name in ("record_date", "notes"):
                    value = formula.get(name)
                    if isinstance(value, dict):
                        yield (
                            f"{formula_id}__{name}",
                            value,
                            image_index,
                            formula.get("record_bbox"),
                        )
                for material_index, material in enumerate(formula.get("materials", []), 1):
                    material_id = material.get("material_id", f"material_{material_index:03d}")
                    for name in ("name", "amount", "unit"):
                        value = material.get(name)
                        if isinstance(value, dict):
                            yield (
                                f"{formula_id}__{material_id}__{name}",
                                value,
                                image_index,
                                formula.get("record_bbox"),
                            )
                for parameter_index, parameter in enumerate(
                    formula.get("process_parameters", []), 1
                ):
                    parameter_id = parameter.get("parameter_id", f"parameter_{parameter_index:03d}")
                    for name in ("name", "value", "unit"):
                        value = parameter.get(name)
                        if isinstance(value, dict):
                            yield (
                                f"{formula_id}__{parameter_id}__{name}",
                                value,
                                image_index,
                                formula.get("record_bbox"),
                            )
