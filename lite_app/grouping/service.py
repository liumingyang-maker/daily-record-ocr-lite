"""配方切分与公司/产品分组服务。"""

from __future__ import annotations

import logging
import re
from typing import Any

from .models import (
    BusinessEntities,
    CompanyGroup,
    EvidenceField,
    Formula,
    FormulaBlock,
    MaterialField,
    PageRecognition,
    ProcessField,
    ProductGroup,
    ProductSection,
    make_formula_id,
    make_page_id,
    make_provisional_id,
)

logger = logging.getLogger(__name__)

# 配方编号模式
_FORMULA_NO_PATTERNS = [
    re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]$"),
    re.compile(r"^[\(（]([0-9]+)[\)）]$"),
    re.compile(r"^([0-9]+)[\.、．]$"),
    re.compile(r"^配方\s*([0-9]+)$"),
    re.compile(r"^第?\s*([0-9]+)\s*[条个组批]?$"),
]

_CIRCLED_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩"


def normalize_formula_no(raw: str) -> str:
    """将配方编号标准化为阿拉伯数字字符串。"""
    raw = raw.strip()
    if not raw:
        return ""
    # 圆圈数字
    if raw in _CIRCLED_NUMBERS:
        return str(_CIRCLED_NUMBERS.index(raw) + 1)
    # 括号数字
    m = re.match(r"^[\(（]([0-9]+)[\)）]$", raw)
    if m:
        return m.group(1)
    # 数字+标点
    m = re.match(r"^([0-9]+)[\.、．]$", raw)
    if m:
        return m.group(1)
    # 配方N
    m = re.match(r"^配方\s*([0-9]+)$", raw)
    if m:
        return m.group(1)
    # 纯数字
    m = re.match(r"^([0-9]+)$", raw)
    if m:
        return m.group(1)
    return ""


def is_formula_number_token(text: str) -> bool:
    """判断文本是否是配方编号。"""
    text = text.strip()
    for pattern in _FORMULA_NO_PATTERNS:
        if pattern.match(text):
            return True
    return False


def build_business_entities(
    job_id: str,
    vlm_result: dict[str, Any],
    ocr_pages: list[dict[str, Any]] | None = None,
) -> BusinessEntities:
    """
    从 VLM 识别结果构建业务实体。

    支持两种 VLM 输出格式：
    1. 新格式：pages[] 结构
    2. 旧格式：records[] 结构（兼容）
    """
    entities = BusinessEntities()

    # 尝试新格式 pages[]
    pages_data = vlm_result.get("pages", [])
    if pages_data:
        _build_from_pages(job_id, entities, pages_data)
    else:
        # 兼容旧格式 records[]
        records = vlm_result.get("records", [])
        _build_from_records(job_id, entities, records, vlm_result.get("page_heading", ""))

    # 构建公司分组
    _build_company_groups(entities)
    # 构建产品分组
    _build_product_groups(entities)
    # 计算配方状态
    _compute_formula_statuses(entities)

    return entities


def _build_from_pages(job_id: str, entities: BusinessEntities, pages_data: list[dict]) -> None:
    """从 pages[] 格式构建。"""
    for i, page_data in enumerate(pages_data, 1):
        page_id = make_page_id(i)
        page = PageRecognition(
            page_id=page_id,
            source_image_index=page_data.get("source_image_index", i),
            source_filename=page_data.get("source_filename", ""),
            company=_parse_evidence_field(page_data.get("company", {})),
            warnings=page_data.get("warnings", []),
        )

        formula_seq = 0
        for ps_data in page_data.get("product_sections", []):
            section = ProductSection(
                product_or_series=_parse_evidence_field(ps_data.get("product_or_series", {})),
                product_type=ps_data.get("product_type", "unknown"),
                section_bbox=ps_data.get("section_bbox"),
            )

            for f_data in ps_data.get("formulas", []):
                formula_seq += 1
                formula = _build_formula(job_id, page_id, page.source_image_index, formula_seq, f_data)
                section.formula_blocks.append(FormulaBlock(
                    formula_id=formula.formula_id,
                    formula_no_raw=formula.formula_no_raw,
                    formula_no_normalized=formula.formula_no_normalized,
                    formula_sequence=formula_seq,
                    bbox=formula.record_bbox,
                ))
                entities.formulas.append(formula)

            page.product_sections.append(section)

        entities.pages.append(page)


def _build_from_records(job_id: str, entities: BusinessEntities, records: list[dict], page_heading: str) -> None:
    """从旧格式 records[] 构建（兼容）。"""
    # 按 source_image_indexes 分组
    pages_map: dict[int, list[dict]] = {}
    for record in records:
        indexes = record.get("source_image_indexes", [1])
        idx = indexes[0] if indexes else 1
        pages_map.setdefault(idx, []).append(record)

    for img_idx in sorted(pages_map.keys()):
        page_id = make_page_id(img_idx)
        page = PageRecognition(
            page_id=page_id,
            source_image_index=img_idx,
            company=EvidenceField(raw_value=page_heading, standard_value=page_heading),
        )

        section = ProductSection(
            product_or_series=EvidenceField(),
            product_type="unknown",
        )

        for seq, record in enumerate(pages_map[img_idx], 1):
            formula = _build_formula_from_record(job_id, page_id, img_idx, seq, record)
            section.formula_blocks.append(FormulaBlock(
                formula_id=formula.formula_id,
                formula_no_raw=formula.formula_no_raw,
                formula_no_normalized=formula.formula_no_normalized,
                formula_sequence=seq,
                bbox=formula.record_bbox,
            ))
            entities.formulas.append(formula)

        page.product_sections.append(section)
        entities.pages.append(page)


def _build_formula(job_id: str, page_id: str, img_idx: int, seq: int, data: dict) -> Formula:
    """从新格式构建配方。"""
    formula_id = make_formula_id(job_id, page_id, seq)
    no_raw = data.get("formula_no", data.get("formula_no_raw", ""))

    formula = Formula(
        formula_id=formula_id,
        page_id=page_id,
        source_image_index=img_idx,
        formula_no_raw=no_raw,
        formula_no_normalized=normalize_formula_no(no_raw),
        formula_sequence=seq,
        record_date=_parse_evidence_field(data.get("record_date", {})),
        record_bbox=data.get("record_bbox"),
        notes=_parse_evidence_field(data.get("notes", {})),
        warnings=data.get("warnings", []),
    )

    for mi, m_data in enumerate(data.get("materials", []), 1):
        formula.materials.append(MaterialField(
            field_id=f"{formula_id}__material_{mi:03d}",
            name=_parse_evidence_field(m_data.get("name", {})),
            amount=_parse_evidence_field(m_data.get("amount", {})),
            unit=_parse_evidence_field(m_data.get("unit", {})),
        ))

    for pi, p_data in enumerate(data.get("process_parameters", []), 1):
        formula.process_parameters.append(ProcessField(
            field_id=f"{formula_id}__process_{pi:03d}",
            name=_parse_evidence_field(p_data.get("name", {})),
            value=_parse_evidence_field(p_data.get("value", {})),
            unit=_parse_evidence_field(p_data.get("unit", {})),
        ))

    return formula


def _build_formula_from_record(job_id: str, page_id: str, img_idx: int, seq: int, record: dict) -> Formula:
    """从旧格式 record 构建配方。"""
    formula_id = make_formula_id(job_id, page_id, seq)

    # 旧格式字段可能是字符串或对象
    date_val = record.get("record_date", "")
    if isinstance(date_val, dict):
        date_field = _parse_evidence_field(date_val)
    else:
        date_field = EvidenceField(raw_value=str(date_val), standard_value=str(date_val))

    formula = Formula(
        formula_id=formula_id,
        page_id=page_id,
        source_image_index=img_idx,
        formula_no_raw="",
        formula_no_normalized="",
        formula_sequence=seq,
        record_date=date_field,
        record_bbox=record.get("record_bbox"),
        warnings=record.get("warnings", []),
    )

    for mi, m in enumerate(record.get("materials", []), 1):
        name_val = m.get("name", "")
        amount_val = m.get("amount", "")
        unit_val = m.get("unit", "")
        formula.materials.append(MaterialField(
            field_id=f"{formula_id}__material_{mi:03d}",
            name=EvidenceField(raw_value=str(name_val) if not isinstance(name_val, dict) else name_val.get("value", ""),
                             confidence=name_val.get("confidence", 0.8) if isinstance(name_val, dict) else 0.8),
            amount=EvidenceField(raw_value=str(amount_val) if not isinstance(amount_val, dict) else amount_val.get("value", ""),
                               confidence=amount_val.get("confidence", 0.8) if isinstance(amount_val, dict) else 0.8),
            unit=EvidenceField(raw_value=str(unit_val) if not isinstance(unit_val, dict) else unit_val.get("value", "")),
        ))

    for pi, p in enumerate(record.get("process_parameters", []), 1):
        name_val = p.get("name", "")
        value_val = p.get("value", "")
        unit_val = p.get("unit", "")
        formula.process_parameters.append(ProcessField(
            field_id=f"{formula_id}__process_{pi:03d}",
            name=EvidenceField(raw_value=str(name_val) if not isinstance(name_val, dict) else name_val.get("value", "")),
            value=EvidenceField(raw_value=str(value_val) if not isinstance(value_val, dict) else value_val.get("value", "")),
            unit=EvidenceField(raw_value=str(unit_val) if not isinstance(unit_val, dict) else unit_val.get("value", "")),
        ))

    return formula


def _build_company_groups(entities: BusinessEntities) -> None:
    """从页面公司构建公司分组（跨页合并）。"""
    # 按标准公司名分组
    company_map: dict[str, CompanyGroup] = {}

    for page in entities.pages:
        raw = page.company.raw_value.strip()
        standard = page.company.standard_value.strip() or raw
        if not raw and not standard:
            continue

        # 用标准名作为分组键
        key = standard or raw
        if key not in company_map:
            company_id = make_provisional_id("company", key)
            company_map[key] = CompanyGroup(
                company_id=company_id,
                display_name=standard or raw,
                raw_names=[],
                confidence=page.company.confidence,
                source_page_ids=[],
                source_image_indexes=[],
                review_status=page.company.review_status,
                match_source=page.company.match_source,
            )

        cg = company_map[key]
        if raw and raw not in cg.raw_names:
            cg.raw_names.append(raw)
        if page.page_id not in cg.source_page_ids:
            cg.source_page_ids.append(page.page_id)
        if page.source_image_index not in cg.source_image_indexes:
            cg.source_image_indexes.append(page.source_image_index)

    entities.company_groups = list(company_map.values())

    # 将配方关联到公司
    for formula in entities.formulas:
        page = next((p for p in entities.pages if p.page_id == formula.page_id), None)
        if page:
            raw = page.company.raw_value.strip()
            standard = page.company.standard_value.strip() or raw
            key = standard or raw
            if key in company_map:
                formula.company_id = company_map[key].company_id


def _build_product_groups(entities: BusinessEntities) -> None:
    """从页面产品区段构建产品分组。"""
    product_map: dict[str, ProductGroup] = {}

    for page in entities.pages:
        company_id = ""
        # 找页面对应的公司
        for cg in entities.company_groups:
            if page.page_id in cg.source_page_ids:
                company_id = cg.company_id
                break

        for section in page.product_sections:
            raw = section.product_or_series.raw_value.strip()
            standard = section.product_or_series.standard_value.strip() or raw
            if not raw and not standard:
                continue

            key = f"{company_id}__{standard or raw}"
            if key not in product_map:
                product_id = make_provisional_id("product", standard or raw)
                product_map[key] = ProductGroup(
                    product_id=product_id,
                    company_id=company_id,
                    display_name=standard or raw,
                    raw_names=[],
                    product_type=section.product_type,
                    confidence=section.product_or_series.confidence,
                    source_page_ids=[],
                    review_status=section.product_or_series.review_status,
                )

            pg = product_map[key]
            if raw and raw not in pg.raw_names:
                pg.raw_names.append(raw)
            if page.page_id not in pg.source_page_ids:
                pg.source_page_ids.append(page.page_id)

    entities.product_groups = list(product_map.values())

    # 将配方关联到产品
    for formula in entities.formulas:
        page = next((p for p in entities.pages if p.page_id == formula.page_id), None)
        if not page:
            continue
        for section in page.product_sections:
            # 检查配方是否在这个 section 中
            for fb in section.formula_blocks:
                if fb.formula_id == formula.formula_id:
                    raw = section.product_or_series.raw_value.strip()
                    standard = section.product_or_series.standard_value.strip() or raw
                    if raw or standard:
                        key = f"{formula.company_id}__{standard or raw}"
                        if key in product_map:
                            formula.product_id = product_map[key].product_id
                    break


def _compute_formula_statuses(entities: BusinessEntities) -> None:
    """计算配方级审查状态。"""
    for formula in entities.formulas:
        conflicts = 0
        low_conf = 0

        # 检查材料字段
        for m in formula.materials:
            if m.amount.review_status == "CONFLICT" or m.name.review_status == "CONFLICT":
                conflicts += 1
            if m.amount.confidence < 0.7 or m.name.confidence < 0.7:
                low_conf += 1

        # 检查工艺字段
        for p in formula.process_parameters:
            if p.value.review_status == "CONFLICT":
                conflicts += 1

        # 检查日期
        if formula.record_date.review_status == "CONFLICT":
            conflicts += 1

        formula.conflict_count = conflicts
        formula.low_confidence_count = low_conf

        if conflicts > 0:
            formula.review_status = "REVIEW_REQUIRED"
        elif not formula.materials:
            formula.review_status = "INCOMPLETE"
        else:
            formula.review_status = "AUTO_ACCEPTED"


def _parse_evidence_field(data: Any) -> EvidenceField:
    """解析证据字段（兼容字符串和对象）。"""
    if not data:
        return EvidenceField()
    if isinstance(data, str):
        return EvidenceField(raw_value=data, standard_value=data)
    if isinstance(data, dict):
        return EvidenceField(
            raw_value=data.get("raw_value", data.get("value", "")),
            standard_value=data.get("standard_value", ""),
            confidence=data.get("confidence", 0.0),
            bbox=data.get("bbox"),
            evidence_token_ids=data.get("evidence_token_ids", []),
            match_source=data.get("match_source", ""),
            review_status=data.get("review_status", "AUTO_ACCEPT"),
        )
    return EvidenceField()
