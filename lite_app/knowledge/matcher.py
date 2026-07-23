"""历史物料匹配器：精确、别名、模糊匹配。"""

from __future__ import annotations

import logging
import re
from typing import Any

from rapidfuzz import fuzz, process

from .database import KnowledgeDB

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """标准化文本用于比较（不覆盖原始值）。"""
    if not text:
        return ""
    # 全角转半角
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            result.append(" ")
        else:
            result.append(ch)
    s = "".join(result)
    # 去多余空格
    s = re.sub(r"\s+", " ", s).strip()
    # 英文统一小写
    s = s.lower()
    # 常见连字符归一
    s = s.replace("－", "-").replace("–", "-").replace("—", "-")
    # 中文括号归一
    s = s.replace("（", "(").replace("）", ")")
    return s


class HistoryMatcher:
    """历史物料和配方匹配器。"""

    def __init__(self, db: KnowledgeDB) -> None:
        self.db = db
        self._materials_cache: list[dict[str, Any]] | None = None
        self._aliases_cache: list[dict[str, Any]] | None = None

    def _load_caches(self) -> None:
        if self._materials_cache is None:
            self._materials_cache = self.db.get_all_materials()
            self._aliases_cache = self.db.get_all_aliases()

    def invalidate_cache(self) -> None:
        self._materials_cache = None
        self._aliases_cache = None

    def match_material(self, text: str, max_candidates: int = 5) -> list[dict[str, Any]]:
        """
        匹配物料名称，返回候选列表。

        匹配顺序：
        1. 原文精确匹配
        2. 标准化后精确匹配
        3. 别名精确匹配
        4. 常见 OCR 错误匹配
        5. RapidFuzz 模糊匹配
        """
        if not text or not text.strip():
            return []

        self._load_caches()
        candidates: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        def _add(name: str, score: float, match_type: str) -> None:
            if name not in seen_names:
                seen_names.add(name)
                candidates.append({
                    "standard_name": name,
                    "score": round(score, 4),
                    "match_type": match_type,
                })

        # 1. 原文精确匹配
        material = self.db.find_material_by_name(text)
        if material:
            _add(material["standard_name"], 1.0, "exact")

        # 2. 标准化后精确匹配
        norm_text = normalize_text(text)
        if norm_text and not candidates:
            for m in (self._materials_cache or []):
                if normalize_text(m["standard_name"]) == norm_text:
                    _add(m["standard_name"], 0.98, "normalized_exact")
                    break

        # 3. 别名精确匹配
        if not candidates:
            for alias in (self._aliases_cache or []):
                if alias["alias"] == text or normalize_text(alias["alias"]) == norm_text:
                    _add(alias["standard_name"], 0.95, "alias_exact")
                    break

        # 4. 常见 OCR 错误匹配（O/0, I/1 等）
        if not candidates:
            ocr_variants = self._generate_ocr_variants(text)
            for variant in ocr_variants:
                for alias in (self._aliases_cache or []):
                    if alias["alias"] == variant and alias.get("alias_type") == "ocr_error":
                        _add(alias["standard_name"], 0.85, "ocr_error_alias")
                        break
                if candidates:
                    break

        # 5. RapidFuzz 模糊匹配
        if len(candidates) < max_candidates:
            all_names = [m["standard_name"] for m in (self._materials_cache or [])]
            if all_names:
                # 短字符串（<=3字符）使用更严格阈值
                min_score = 90 if len(text) <= 3 else 75
                results = process.extract(
                    norm_text,
                    {normalize_text(n): n for n in all_names},
                    scorer=fuzz.ratio,
                    limit=max_candidates,
                    score_cutoff=min_score,
                )
                for match_text, score, _ in results:
                    original_name = {normalize_text(n): n for n in all_names}.get(match_text, match_text)
                    _add(original_name, score / 100.0, "fuzzy")

        return candidates[:max_candidates]

    def match_formula(self, materials: list[str], title: str = "", max_candidates: int = 3) -> list[dict[str, Any]]:
        """匹配历史配方，返回相似度排序的候选。"""
        self._load_caches()
        formulas = self.db.get_all_formulas()
        if not formulas or not materials:
            return []

        candidates: list[dict[str, Any]] = []
        input_set = set(normalize_text(m) for m in materials if m)

        for formula in formulas:
            items = self.db.get_formula_items(formula["id"])
            if not items:
                continue

            formula_materials = set(
                normalize_text(item["material_name"]) for item in items if item["material_name"]
            )

            # Jaccard 相似度
            if not formula_materials:
                continue
            intersection = input_set & formula_materials
            union = input_set | formula_materials
            jaccard = len(intersection) / len(union) if union else 0

            # 标题相似度
            title_score = 0.0
            if title and formula.get("title"):
                title_score = fuzz.ratio(
                    normalize_text(title), normalize_text(formula["title"])
                ) / 100.0

            # 综合分数
            combined = jaccard * 0.7 + title_score * 0.3

            if combined > 0.3:
                candidates.append({
                    "formula_id": formula["id"],
                    "title": formula.get("title", ""),
                    "score": round(combined, 4),
                    "jaccard": round(jaccard, 4),
                    "items": [
                        {"material_name": i["material_name"], "amount": i["amount"], "unit": i["unit"]}
                        for i in items
                    ],
                })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:max_candidates]

    @staticmethod
    def _generate_ocr_variants(text: str) -> list[str]:
        """生成常见 OCR 错误变体。"""
        variants = []
        # O <-> 0
        if "O" in text or "o" in text:
            variants.append(text.replace("O", "0").replace("o", "0"))
        if "0" in text:
            variants.append(text.replace("0", "O"))
        # I <-> 1, l <-> 1
        if "I" in text or "l" in text:
            variants.append(text.replace("I", "1").replace("l", "1"))
        if "1" in text:
            variants.append(text.replace("1", "I"))
        return variants
