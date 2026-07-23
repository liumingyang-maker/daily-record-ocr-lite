"""业务分组数据模型：PageRecognition / Company / Product / Formula。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


# ─── 稳定 ID 生成 ───────────────────────────────────────────


def make_page_id(image_index: int) -> str:
    """按上传顺序生成页面 ID。"""
    return f"page_{image_index:03d}"


def make_formula_id(job_id: str, page_id: str, sequence: int) -> str:
    """配方稳定唯一 ID：即使公司/产品/编号修改也不变。"""
    return f"{job_id}__{page_id}__formula_{sequence:03d}"


def make_field_id(formula_id: str, field_type: str, index: int, sub_field: str) -> str:
    """字段稳定 ID。"""
    return f"{formula_id}__{field_type}_{index:03d}__{sub_field}"


def make_provisional_id(prefix: str, raw_value: str) -> str:
    """临时公司/产品 ID（尚未确认时）。"""
    h = hashlib.md5(raw_value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_provisional_{h}"


# ─── 证据字段 ───────────────────────────────────────────────


@dataclass
class EvidenceField:
    """带证据的字段值。"""
    raw_value: str = ""
    standard_value: str = ""
    confidence: float = 0.0
    bbox: list[float] | None = None  # [x_min, y_min, x_max, y_max] 归一化
    evidence_token_ids: list[str] = field(default_factory=list)
    match_source: str = ""  # history_exact, alias, fuzzy, vlm, ocr
    review_status: str = "AUTO_ACCEPT"  # AUTO_ACCEPT, NEED_REVIEW, MANUAL_CONFIRMED


# ─── 页面级识别 ─────────────────────────────────────────────


@dataclass
class FormulaBlock:
    """页面内的配方块（切分结果）。"""
    formula_id: str = ""
    formula_no_raw: str = ""  # ①, ②, 1., 配方1
    formula_no_normalized: str = ""  # 1, 2, 3
    formula_sequence: int = 0  # 页面内从上到下顺序
    bbox: list[float] | None = None  # 归一化坐标


@dataclass
class ProductSection:
    """页面内的产品/系列区段。"""
    product_or_series: EvidenceField = field(default_factory=EvidenceField)
    product_type: str = "unknown"  # product, series, material_grade, category, unknown
    section_bbox: list[float] | None = None
    formula_blocks: list[FormulaBlock] = field(default_factory=list)


@dataclass
class PageRecognition:
    """单页识别结果。"""
    page_id: str = ""
    source_image_index: int = 0
    source_filename: str = ""
    page_bbox: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])

    company: EvidenceField = field(default_factory=EvidenceField)
    product_sections: list[ProductSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ─── 业务实体（扁平存储）─────────────────────────────────────


@dataclass
class CompanyGroup:
    """公司分组（跨页合并后的业务实体）。"""
    company_id: str = ""
    display_name: str = ""  # 标准名
    raw_names: list[str] = field(default_factory=list)  # 所有原文
    confidence: float = 0.0
    source_page_ids: list[str] = field(default_factory=list)
    source_image_indexes: list[int] = field(default_factory=list)
    review_status: str = "AUTO_ACCEPT"
    match_source: str = ""


@dataclass
class ProductGroup:
    """产品/系列分组。"""
    product_id: str = ""
    company_id: str = ""
    display_name: str = ""
    raw_names: list[str] = field(default_factory=list)
    product_type: str = "unknown"
    confidence: float = 0.0
    source_page_ids: list[str] = field(default_factory=list)
    review_status: str = "AUTO_ACCEPT"


@dataclass
class MaterialField:
    """原料字段。"""
    field_id: str = ""
    name: EvidenceField = field(default_factory=EvidenceField)
    amount: EvidenceField = field(default_factory=EvidenceField)
    unit: EvidenceField = field(default_factory=EvidenceField)


@dataclass
class ProcessField:
    """工艺参数字段。"""
    field_id: str = ""
    name: EvidenceField = field(default_factory=EvidenceField)
    value: EvidenceField = field(default_factory=EvidenceField)
    unit: EvidenceField = field(default_factory=EvidenceField)


@dataclass
class Formula:
    """配方业务实体。"""
    formula_id: str = ""
    page_id: str = ""
    source_image_index: int = 0
    company_id: str = ""
    product_id: str = ""

    formula_no_raw: str = ""
    formula_no_normalized: str = ""
    formula_sequence: int = 0

    record_date: EvidenceField = field(default_factory=EvidenceField)
    record_bbox: list[float] | None = None

    materials: list[MaterialField] = field(default_factory=list)
    process_parameters: list[ProcessField] = field(default_factory=list)
    notes: EvidenceField = field(default_factory=EvidenceField)

    review_status: str = "AUTO_ACCEPTED"  # AUTO_ACCEPTED, REVIEW_REQUIRED, MANUAL_CONFIRMED, INCOMPLETE
    conflict_count: int = 0
    low_confidence_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class BusinessEntities:
    """任务级业务实体集合（扁平存储）。"""
    pages: list[PageRecognition] = field(default_factory=list)
    company_groups: list[CompanyGroup] = field(default_factory=list)
    product_groups: list[ProductGroup] = field(default_factory=list)
    formulas: list[Formula] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 可写字典。"""
        import dataclasses

        def _convert(obj: Any) -> Any:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, list):
                return [_convert(i) for i in obj]
            return obj

        return {
            "pages": _convert(self.pages),
            "company_groups": _convert(self.company_groups),
            "product_groups": _convert(self.product_groups),
            "formulas": _convert(self.formulas),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BusinessEntities":
        """从字典反序列化。"""
        entities = cls()

        for p in data.get("pages", []):
            page = PageRecognition(
                page_id=p.get("page_id", ""),
                source_image_index=p.get("source_image_index", 0),
                source_filename=p.get("source_filename", ""),
                page_bbox=p.get("page_bbox", [0, 0, 1, 1]),
                company=_parse_evidence(p.get("company", {})),
                warnings=p.get("warnings", []),
            )
            for ps in p.get("product_sections", []):
                section = ProductSection(
                    product_or_series=_parse_evidence(ps.get("product_or_series", {})),
                    product_type=ps.get("product_type", "unknown"),
                    section_bbox=ps.get("section_bbox"),
                )
                for fb in ps.get("formula_blocks", []):
                    section.formula_blocks.append(FormulaBlock(
                        formula_id=fb.get("formula_id", ""),
                        formula_no_raw=fb.get("formula_no_raw", ""),
                        formula_no_normalized=fb.get("formula_no_normalized", ""),
                        formula_sequence=fb.get("formula_sequence", 0),
                        bbox=fb.get("bbox"),
                    ))
                page.product_sections.append(section)
            entities.pages.append(page)

        for cg in data.get("company_groups", []):
            entities.company_groups.append(CompanyGroup(
                company_id=cg.get("company_id", ""),
                display_name=cg.get("display_name", ""),
                raw_names=cg.get("raw_names", []),
                confidence=cg.get("confidence", 0),
                source_page_ids=cg.get("source_page_ids", []),
                source_image_indexes=cg.get("source_image_indexes", []),
                review_status=cg.get("review_status", "AUTO_ACCEPT"),
                match_source=cg.get("match_source", ""),
            ))

        for pg in data.get("product_groups", []):
            entities.product_groups.append(ProductGroup(
                product_id=pg.get("product_id", ""),
                company_id=pg.get("company_id", ""),
                display_name=pg.get("display_name", ""),
                raw_names=pg.get("raw_names", []),
                product_type=pg.get("product_type", "unknown"),
                confidence=pg.get("confidence", 0),
                source_page_ids=pg.get("source_page_ids", []),
                review_status=pg.get("review_status", "AUTO_ACCEPT"),
            ))

        for f in data.get("formulas", []):
            formula = Formula(
                formula_id=f.get("formula_id", ""),
                page_id=f.get("page_id", ""),
                source_image_index=f.get("source_image_index", 0),
                company_id=f.get("company_id", ""),
                product_id=f.get("product_id", ""),
                formula_no_raw=f.get("formula_no_raw", ""),
                formula_no_normalized=f.get("formula_no_normalized", ""),
                formula_sequence=f.get("formula_sequence", 0),
                record_date=_parse_evidence(f.get("record_date", {})),
                record_bbox=f.get("record_bbox"),
                notes=_parse_evidence(f.get("notes", {})),
                review_status=f.get("review_status", "AUTO_ACCEPTED"),
                conflict_count=f.get("conflict_count", 0),
                low_confidence_count=f.get("low_confidence_count", 0),
                warnings=f.get("warnings", []),
            )
            for m in f.get("materials", []):
                formula.materials.append(MaterialField(
                    field_id=m.get("field_id", ""),
                    name=_parse_evidence(m.get("name", {})),
                    amount=_parse_evidence(m.get("amount", {})),
                    unit=_parse_evidence(m.get("unit", {})),
                ))
            for pp in f.get("process_parameters", []):
                formula.process_parameters.append(ProcessField(
                    field_id=pp.get("field_id", ""),
                    name=_parse_evidence(pp.get("name", {})),
                    value=_parse_evidence(pp.get("value", {})),
                    unit=_parse_evidence(pp.get("unit", {})),
                ))
            entities.formulas.append(formula)

        return entities

    def get_summary(self) -> dict[str, Any]:
        """计算任务摘要。"""
        auto_accepted = sum(1 for f in self.formulas if f.review_status == "AUTO_ACCEPTED")
        review_required = sum(1 for f in self.formulas if f.review_status in ("REVIEW_REQUIRED", "INCOMPLETE"))
        conflict_fields = sum(f.conflict_count for f in self.formulas)

        return {
            "image_count": len(set(p.source_image_index for p in self.pages)),
            "company_count": len(self.company_groups),
            "product_count": len(self.product_groups),
            "formula_count": len(self.formulas),
            "auto_accepted_formula_count": auto_accepted,
            "review_formula_count": review_required,
            "conflict_field_count": conflict_fields,
        }

    def build_company_tree(self) -> list[dict[str, Any]]:
        """组装公司树（用于 UI）。"""
        tree = []
        for cg in self.company_groups:
            company_node = {
                "company_id": cg.company_id,
                "display_name": cg.display_name,
                "raw_names": cg.raw_names,
                "source_image_indexes": cg.source_image_indexes,
                "review_status": cg.review_status,
                "products": [],
            }
            # 找该公司下的产品
            company_products = [pg for pg in self.product_groups if pg.company_id == cg.company_id]
            for pg in company_products:
                product_node = {
                    "product_id": pg.product_id,
                    "display_name": pg.display_name,
                    "product_type": pg.product_type,
                    "review_status": pg.review_status,
                    "formulas": [],
                }
                # 找该产品下的配方
                product_formulas = [f for f in self.formulas if f.product_id == pg.product_id]
                for f in product_formulas:
                    product_node["formulas"].append(_formula_summary(f))
                company_node["products"].append(product_node)

            # 没有产品的配方直接挂公司下
            orphan_formulas = [
                f for f in self.formulas
                if f.company_id == cg.company_id and not f.product_id
            ]
            if orphan_formulas:
                company_node["products"].append({
                    "product_id": "",
                    "display_name": "未分类产品/系列",
                    "product_type": "unknown",
                    "review_status": "AUTO_ACCEPT",
                    "formulas": [_formula_summary(f) for f in orphan_formulas],
                })

            tree.append(company_node)
        return tree


def _formula_summary(f: Formula) -> dict[str, Any]:
    """配方摘要（用于树形展示）。"""
    return {
        "formula_id": f.formula_id,
        "formula_no_raw": f.formula_no_raw,
        "formula_no_normalized": f.formula_no_normalized,
        "formula_sequence": f.formula_sequence,
        "record_date": f.record_date.raw_value,
        "source_image_index": f.source_image_index,
        "page_id": f.page_id,
        "review_status": f.review_status,
        "conflict_count": f.conflict_count,
        "material_count": len(f.materials),
        "process_count": len(f.process_parameters),
    }


def _parse_evidence(data: dict[str, Any]) -> EvidenceField:
    """解析证据字段。"""
    if not data:
        return EvidenceField()
    return EvidenceField(
        raw_value=data.get("raw_value", data.get("value", "")),
        standard_value=data.get("standard_value", ""),
        confidence=data.get("confidence", 0.0),
        bbox=data.get("bbox"),
        evidence_token_ids=data.get("evidence_token_ids", []),
        match_source=data.get("match_source", ""),
        review_status=data.get("review_status", "AUTO_ACCEPT"),
    )
