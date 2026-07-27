"""Grouping review operations backed by FinalResult or a formal review overlay."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..config import DATA_ROOT
from ..final_result import FinalResultService
from ..storage import read_json_optional, write_json_atomic
from .models import BusinessEntities
from .service import build_business_entities


class GroupingReviewError(RuntimeError):
    """A requested grouping edit is invalid."""


def build_reviewed_business_entities(
    job_dir: Path,
    job_id: str,
    final: dict[str, Any],
) -> BusinessEntities:
    entities = build_business_entities(job_id, final)
    overlay = read_json_optional(job_dir / "review" / "group_overrides.json")
    if not isinstance(overlay, dict):
        return entities

    company_merges = overlay.get("company_merges", {})
    product_merges = overlay.get("product_merges", {})
    formula_groups = overlay.get("formula_groups", {})

    for formula in entities.formulas:
        group = formula_groups.get(formula.formula_id, {})
        if group.get("company_id"):
            formula.company_id = str(group["company_id"])
        if group.get("product_id"):
            formula.product_id = str(group["product_id"])
        formula.company_id = _resolve_merge(formula.company_id, company_merges)
        formula.product_id = _resolve_merge(formula.product_id, product_merges)

    for product in entities.product_groups:
        product.company_id = _resolve_merge(product.company_id, company_merges)
    entities.company_groups = _merge_company_entities(entities.company_groups, company_merges)
    entities.product_groups = _merge_product_entities(entities.product_groups, product_merges)
    return entities


class GroupingReviewService:
    def __init__(
        self,
        job_dir: Path,
        job_id: str,
        knowledge_db_path: Path | None = None,
    ) -> None:
        self.job_dir = job_dir
        self.job_id = job_id
        self.final_service = FinalResultService(job_dir)
        self.overlay_path = job_dir / "review" / "group_overrides.json"
        self.knowledge_db_path = knowledge_db_path or DATA_ROOT / "knowledge.sqlite3"

    def update_page_company(
        self,
        page_id: str,
        raw_value: str,
        standard_value: str,
    ) -> None:
        final = self.final_service.load()
        page = next(
            (item for item in final.get("pages", []) if item.get("page_id") == page_id),
            None,
        )
        if page is None:
            raise GroupingReviewError(f"页面不存在: {page_id}")
        company = page["company"]
        company["raw_value"] = raw_value
        company["standard_value"] = standard_value or raw_value
        company["review_status"] = "MANUAL_CONFIRMED"
        company["confidence"] = 1.0
        company["match_source"] = "manual"
        self.final_service.replace(final)

    def update_formula_number(self, formula_id: str, formula_no: str) -> None:
        final = self.final_service.load()
        _, _, formula = _locate_formula(final, formula_id)
        formula["formula_no"] = formula_no
        self.final_service.replace(final)

    def merge_formulas(self, formula_ids: list[str]) -> str:
        if len(formula_ids) < 2:
            raise GroupingReviewError("至少需要两条配方才能合并")
        final = self.final_service.load()
        locations = [_locate_formula(final, formula_id) for formula_id in formula_ids]
        containers = {id(container) for container, _, _ in locations}
        if len(containers) != 1:
            raise GroupingReviewError("只能合并同一产品区段中的配方")
        locations.sort(key=lambda item: item[1])
        container = locations[0][0]
        base = locations[0][2]
        for _, _, other in locations[1:]:
            base["materials"].extend(other.get("materials", []))
            base["process_parameters"].extend(other.get("process_parameters", []))
            other_notes = other.get("notes", {}).get("value", "")
            if other_notes:
                current = base.get("notes", {}).get("value", "")
                base["notes"]["value"] = f"{current} {other_notes}".strip()
            base.setdefault("warnings", []).extend(other.get("warnings", []))
        for _, index, _ in sorted(locations[1:], key=lambda item: item[1], reverse=True):
            container.pop(index)
        _resequence(final)
        field_id_mapping = _rekey_formula_fields(final)
        formula_mapping = {
            str(formula["formula_id"]): str(base["formula_id"]) for _, _, formula in locations[1:]
        }
        self._remap_formula_groups(formula_mapping)
        self._sync_fusion_field_ids(final, field_id_mapping)
        self._sync_correction_field_ids(final, field_id_mapping, formula_mapping)
        self.final_service.replace(final)
        return str(base["formula_id"])

    def split_formula(self, formula_id: str, split_after: int) -> str:
        final = self.final_service.load()
        container, index, formula = _locate_formula(final, formula_id)
        materials = formula.get("materials", [])
        if split_after <= 0 or split_after >= len(materials):
            raise GroupingReviewError("拆分位置无效")
        new_formula = copy.deepcopy(formula)
        suffix = 1
        existing = {
            item.get("formula_id")
            for page in final.get("pages", [])
            for section in page.get("product_sections", [])
            for item in section.get("formulas", [])
        }
        while f"{formula_id}__split_{suffix:03d}" in existing:
            suffix += 1
        new_formula["formula_id"] = f"{formula_id}__split_{suffix:03d}"
        new_formula["formula_no"] = ""
        new_formula["materials"] = materials[split_after:]
        new_formula["process_parameters"] = []
        new_formula.setdefault("warnings", []).append("由人工拆分操作创建")
        formula["materials"] = materials[:split_after]
        formula.setdefault("warnings", []).append("由人工拆分操作截断")
        container.insert(index + 1, new_formula)
        _resequence(final)
        field_id_mapping = _rekey_formula_fields(final)
        self._copy_formula_group(formula_id, str(new_formula["formula_id"]))
        self._sync_fusion_field_ids(final, field_id_mapping)
        self._sync_correction_field_ids(final, field_id_mapping, {})
        self.final_service.replace(final)
        return str(new_formula["formula_id"])

    def update_formula_group(
        self,
        formula_id: str,
        company_id: str | None,
        product_id: str | None,
    ) -> None:
        _locate_formula(self.final_service.load(), formula_id)
        overlay = self._load_overlay()
        group = overlay["formula_groups"].setdefault(formula_id, {})
        if company_id is not None:
            group["company_id"] = company_id
        if product_id is not None:
            group["product_id"] = product_id
        self._save_overlay(overlay)

    def merge_company(self, source_id: str, target_id: str) -> None:
        overlay = self._load_overlay()
        overlay["company_merges"][source_id] = target_id
        self._save_overlay(overlay)

    def merge_product(self, source_id: str, target_id: str) -> None:
        overlay = self._load_overlay()
        overlay["product_merges"][source_id] = target_id
        self._save_overlay(overlay)

    def _load_overlay(self) -> dict[str, Any]:
        overlay = read_json_optional(self.overlay_path)
        if not isinstance(overlay, dict):
            overlay = {}
        overlay.setdefault("schema_version", "group-overrides-v1")
        overlay.setdefault("formula_groups", {})
        overlay.setdefault("company_merges", {})
        overlay.setdefault("product_merges", {})
        return overlay

    def _save_overlay(self, overlay: dict[str, Any]) -> None:
        write_json_atomic(self.overlay_path, overlay)
        final = self.final_service.load()
        self.final_service.replace(final)

    def _remap_formula_groups(self, formula_mapping: dict[str, str]) -> None:
        overlay = self._load_overlay()
        groups = overlay["formula_groups"]
        changed = False
        for source_id, target_id in formula_mapping.items():
            source = groups.pop(source_id, None)
            if source is not None:
                groups.setdefault(target_id, source)
                changed = True
        if changed:
            write_json_atomic(self.overlay_path, overlay)

    def _copy_formula_group(self, source_id: str, target_id: str) -> None:
        overlay = self._load_overlay()
        source = overlay["formula_groups"].get(source_id)
        if source is not None and target_id not in overlay["formula_groups"]:
            overlay["formula_groups"][target_id] = copy.deepcopy(source)
            write_json_atomic(self.overlay_path, overlay)

    def _sync_fusion_field_ids(
        self,
        final: dict[str, Any],
        field_id_mapping: dict[str, str],
    ) -> None:
        path = self.job_dir / "fusion" / "result.json"
        fusion = read_json_optional(path)
        if not isinstance(fusion, dict):
            return
        valid_ids = _final_field_ids(final)
        synchronized = []
        seen: set[str] = set()
        for item in fusion.get("fields", []):
            if not isinstance(item, dict):
                continue
            old_id = str(item.get("field_id", ""))
            new_id = field_id_mapping.get(old_id, old_id)
            if new_id not in valid_ids or new_id in seen:
                continue
            updated = copy.deepcopy(item)
            updated["field_id"] = new_id
            synchronized.append(updated)
            seen.add(new_id)
        fusion["fields"] = synchronized
        write_json_atomic(path, fusion)

    def _sync_correction_field_ids(
        self,
        final: dict[str, Any],
        field_id_mapping: dict[str, str],
        formula_mapping: dict[str, str],
    ) -> None:
        valid_ids = _final_field_ids(final)
        effective_mapping = dict(field_id_mapping)
        for old_formula_id, new_formula_id in formula_mapping.items():
            for name in ("record_date", "notes"):
                effective_mapping.setdefault(
                    f"{old_formula_id}__{name}",
                    f"{new_formula_id}__{name}",
                )

        path = self.job_dir / "review" / "corrections.json"
        corrections = read_json_optional(path)
        changed = False
        if isinstance(corrections, list):
            for correction in corrections:
                if not isinstance(correction, dict):
                    continue
                old_id = str(correction.get("field_id", ""))
                new_id = effective_mapping.get(old_id)
                if not new_id or new_id not in valid_ids:
                    continue
                correction.setdefault("original_field_id", old_id)
                correction["field_id"] = new_id
                record_id = str(correction.get("record_id", ""))
                if record_id in formula_mapping:
                    correction["record_id"] = formula_mapping[record_id]
                changed = True
            if changed:
                write_json_atomic(path, corrections)

        if self.knowledge_db_path.exists():
            from ..knowledge.database import KnowledgeDB

            database = KnowledgeDB(self.knowledge_db_path)
            try:
                database.initialize()
                database.remap_correction_field_ids(
                    self.job_id,
                    effective_mapping,
                    formula_mapping,
                )
            finally:
                database.close()


def _locate_formula(
    final: dict[str, Any],
    formula_id: str,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    for page in final.get("pages", []):
        for section in page.get("product_sections", []):
            formulas = section.get("formulas", [])
            for index, formula in enumerate(formulas):
                if formula.get("formula_id") == formula_id:
                    return formulas, index, formula
    raise GroupingReviewError(f"配方不存在: {formula_id}")


def _resequence(final: dict[str, Any]) -> None:
    for page in final.get("pages", []):
        sequence = 1
        for section in page.get("product_sections", []):
            for formula in section.get("formulas", []):
                formula["formula_sequence"] = sequence
                sequence += 1


def _rekey_formula_fields(final: dict[str, Any]) -> dict[str, str]:
    """Canonicalize nested IDs after structural review operations."""
    pairs: list[tuple[dict[str, Any], str, str]] = []
    old_counts: dict[str, int] = {}

    def collect(field: Any, new_id: str) -> None:
        if not isinstance(field, dict):
            return
        old_id = str(field.get("field_id", ""))
        pairs.append((field, old_id, new_id))
        if old_id:
            old_counts[old_id] = old_counts.get(old_id, 0) + 1

    for page in final.get("pages", []):
        for section in page.get("product_sections", []):
            for formula in section.get("formulas", []):
                formula_id = str(formula.get("formula_id", ""))
                for name in ("record_date", "notes"):
                    collect(formula.get(name), f"{formula_id}__{name}")
                for position, material in enumerate(formula.get("materials", []), 1):
                    material_id = f"material_{position:03d}"
                    material["material_id"] = material_id
                    for name in ("name", "amount", "unit"):
                        collect(
                            material.get(name),
                            f"{formula_id}__{material_id}__{name}",
                        )
                for position, parameter in enumerate(formula.get("process_parameters", []), 1):
                    parameter_id = f"parameter_{position:03d}"
                    parameter["parameter_id"] = parameter_id
                    for name in ("name", "value", "unit"):
                        collect(
                            parameter.get(name),
                            f"{formula_id}__{parameter_id}__{name}",
                        )

    mapping: dict[str, str] = {}
    for field, old_id, new_id in pairs:
        if old_id and old_id != new_id and old_counts[old_id] == 1:
            mapping[old_id] = new_id
        field["field_id"] = new_id
    return mapping


def _final_field_ids(final: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for page in final.get("pages", []):
        for section in page.get("product_sections", []):
            product = section.get("product_or_series")
            if isinstance(product, dict) and product.get("field_id"):
                ids.add(str(product["field_id"]))
            for formula in section.get("formulas", []):
                for name in ("record_date", "notes"):
                    field = formula.get(name)
                    if isinstance(field, dict) and field.get("field_id"):
                        ids.add(str(field["field_id"]))
                for material in formula.get("materials", []):
                    for name in ("name", "amount", "unit"):
                        field = material.get(name)
                        if isinstance(field, dict) and field.get("field_id"):
                            ids.add(str(field["field_id"]))
                for parameter in formula.get("process_parameters", []):
                    for name in ("name", "value", "unit"):
                        field = parameter.get(name)
                        if isinstance(field, dict) and field.get("field_id"):
                            ids.add(str(field["field_id"]))
    return ids


def _resolve_merge(identifier: str, mapping: dict[str, str]) -> str:
    seen = set()
    while identifier in mapping and identifier not in seen:
        seen.add(identifier)
        identifier = mapping[identifier]
    return identifier


def _merge_company_entities(companies, mapping):
    by_id = {company.company_id: company for company in companies}
    for source_id, raw_target_id in mapping.items():
        target_id = _resolve_merge(raw_target_id, mapping)
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if source is None or target is None or source is target:
            continue
        target.raw_names = list(dict.fromkeys([*target.raw_names, *source.raw_names]))
        target.source_page_ids = list(
            dict.fromkeys([*target.source_page_ids, *source.source_page_ids])
        )
        target.source_image_indexes = list(
            dict.fromkeys([*target.source_image_indexes, *source.source_image_indexes])
        )
        companies = [company for company in companies if company.company_id != source_id]
    return companies


def _merge_product_entities(products, mapping):
    by_id = {product.product_id: product for product in products}
    for source_id, raw_target_id in mapping.items():
        target_id = _resolve_merge(raw_target_id, mapping)
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if source is None or target is None or source is target:
            continue
        target.raw_names = list(dict.fromkeys([*target.raw_names, *source.raw_names]))
        target.source_page_ids = list(
            dict.fromkeys([*target.source_page_ids, *source.source_page_ids])
        )
        products = [product for product in products if product.product_id != source_id]
    return products
