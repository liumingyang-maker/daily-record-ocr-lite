"""业务实体存储：business_entities.json 读写。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..storage import write_json_atomic
from .models import BusinessEntities

logger = logging.getLogger(__name__)


def save_business_entities(job_dir: Path, entities: BusinessEntities) -> None:
    """保存业务实体到 review/business_entities.json（原子写入）。"""
    review_dir = job_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    target = review_dir / "business_entities.json"

    write_json_atomic(target, entities.to_dict())


def load_business_entities(job_dir: Path) -> BusinessEntities | None:
    """加载业务实体。不存在时返回 None。"""
    target = job_dir / "review" / "business_entities.json"
    if not target.exists():
        return None
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
        return BusinessEntities.from_dict(data)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("加载 business_entities.json 失败: %s", e)
        return None


def build_tree_response(entities: BusinessEntities) -> dict[str, Any]:
    """构建 /api/jobs/{id}/tree 响应。"""
    return {
        "summary": entities.get_summary(),
        "companies": entities.build_company_tree(),
    }


def build_pages_response(entities: BusinessEntities) -> list[dict[str, Any]]:
    """构建 /api/jobs/{id}/pages 响应。"""

    pages = []
    for page in entities.pages:
        page_dict = {
            "page_id": page.page_id,
            "source_image_index": page.source_image_index,
            "source_filename": page.source_filename,
            "company": {
                "raw_value": page.company.raw_value,
                "standard_value": page.company.standard_value,
                "confidence": page.company.confidence,
                "review_status": page.company.review_status,
            },
            "product_sections": [],
            "warnings": page.warnings,
        }
        for section in page.product_sections:
            section_dict = {
                "product_or_series": {
                    "raw_value": section.product_or_series.raw_value,
                    "standard_value": section.product_or_series.standard_value,
                    "confidence": section.product_or_series.confidence,
                },
                "product_type": section.product_type,
                "section_bbox": section.section_bbox,
                "formula_blocks": [
                    {
                        "formula_id": fb.formula_id,
                        "formula_no_raw": fb.formula_no_raw,
                        "formula_no_normalized": fb.formula_no_normalized,
                        "formula_sequence": fb.formula_sequence,
                        "bbox": fb.bbox,
                    }
                    for fb in section.formula_blocks
                ],
            }
            page_dict["product_sections"].append(section_dict)
        pages.append(page_dict)
    return pages


def build_formula_detail(entities: BusinessEntities, formula_id: str) -> dict[str, Any] | None:
    """构建 /api/jobs/{id}/formulas/{formula_id} 响应。"""
    formula = next((f for f in entities.formulas if f.formula_id == formula_id), None)
    if not formula:
        return None


    def _evidence_to_dict(ev) -> dict:
        return {
            "raw_value": ev.raw_value,
            "standard_value": ev.standard_value,
            "confidence": ev.confidence,
            "bbox": ev.bbox,
            "evidence_token_ids": ev.evidence_token_ids,
            "match_source": ev.match_source,
            "review_status": ev.review_status,
        }

    return {
        "formula_id": formula.formula_id,
        "page_id": formula.page_id,
        "source_image_index": formula.source_image_index,
        "company_id": formula.company_id,
        "product_id": formula.product_id,
        "formula_no_raw": formula.formula_no_raw,
        "formula_no_normalized": formula.formula_no_normalized,
        "formula_sequence": formula.formula_sequence,
        "record_date": _evidence_to_dict(formula.record_date),
        "record_bbox": formula.record_bbox,
        "materials": [
            {
                "field_id": m.field_id,
                "name": _evidence_to_dict(m.name),
                "amount": _evidence_to_dict(m.amount),
                "unit": _evidence_to_dict(m.unit),
            }
            for m in formula.materials
        ],
        "process_parameters": [
            {
                "field_id": p.field_id,
                "name": _evidence_to_dict(p.name),
                "value": _evidence_to_dict(p.value),
                "unit": _evidence_to_dict(p.unit),
            }
            for p in formula.process_parameters
        ],
        "notes": _evidence_to_dict(formula.notes),
        "review_status": formula.review_status,
        "conflict_count": formula.conflict_count,
        "low_confidence_count": formula.low_confidence_count,
        "warnings": formula.warnings,
    }
