"""候选融合引擎：多来源候选合并、冲突检测、置信度计算。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..knowledge.matcher import normalize_text

logger = logging.getLogger(__name__)

# 字段状态
AUTO_ACCEPT = "AUTO_ACCEPT"
NEED_REVIEW = "NEED_REVIEW"
CONFLICT = "CONFLICT"
EMPTY = "EMPTY"
MANUAL_CONFIRMED = "MANUAL_CONFIRMED"


@dataclass
class Candidate:
    """单个候选值。"""
    value: str
    normalized_value: str
    source: str  # ocr_base, ocr_enhanced, vlm, history_material, history_formula, rule, manual
    confidence: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class FusedField:
    """融合后的字段。"""
    field_id: str
    field_type: str  # text, amount, unit, model_code, date
    raw_candidates: list[Candidate] = field(default_factory=list)
    final_value: str = ""
    final_confidence: float = 0.0
    final_source: str = ""
    status: str = EMPTY
    reasons: list[str] = field(default_factory=list)


class FusionEngine:
    """候选融合引擎。"""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = rules or {}
        self._text_rules = self.rules.get("rules", {}).get("text", {})
        self._numeric_rules = self.rules.get("rules", {}).get("numeric", {})
        self._model_rules = self.rules.get("rules", {}).get("model_code", {})
        self._conf_rules = self.rules.get("confidence", {})

        self.auto_accept_threshold = self._conf_rules.get("auto_accept_threshold", 0.90)
        self.review_threshold = self._conf_rules.get("review_score", 0.70)
        self.agree_bonus = self._text_rules.get("ocr_vlm_exact_agreement_bonus", 0.12)
        self.numeric_agree_bonus = self._numeric_rules.get("exact_agreement_bonus", 0.15)
        self.low_ocr_penalty = self._text_rules.get("low_ocr_penalty", 0.15)
        self.low_ocr_threshold = self._text_rules.get("low_ocr_threshold", 0.60)

    def fuse_field(
        self,
        field_id: str,
        field_type: str,
        candidates: list[Candidate],
    ) -> FusedField:
        """融合单个字段的多个候选。"""
        fused = FusedField(
            field_id=field_id,
            field_type=field_type,
            raw_candidates=candidates,
        )

        if not candidates:
            fused.status = EMPTY
            fused.final_value = ""
            fused.reasons.append("无任何候选来源")
            return fused

        # 按字段类型分发
        if field_type in ("amount", "numeric"):
            return self._fuse_numeric(fused)
        elif field_type == "model_code":
            return self._fuse_model_code(fused)
        elif field_type == "date":
            return self._fuse_date(fused)
        else:
            return self._fuse_text(fused)

    def _fuse_text(self, fused: FusedField) -> FusedField:
        """文字字段融合。"""
        candidates = fused.raw_candidates

        # 按标准化值分组
        groups: dict[str, list[Candidate]] = {}
        for c in candidates:
            key = c.normalized_value or c.value
            groups.setdefault(key, []).append(c)

        # 找最大一致组
        best_group_key = max(groups, key=lambda k: len(groups[k]))
        best_group = groups[best_group_key]

        # 计算基础置信度（取最高）
        base_conf = max(c.confidence for c in best_group)

        # OCR 与 VLM 一致加分
        sources = {c.source for c in best_group}
        has_ocr = any(s.startswith("ocr") for s in sources)
        has_vlm = "vlm" in sources

        if has_ocr and has_vlm:
            base_conf = min(base_conf + self.agree_bonus, 0.98)
            fused.final_source = "ocr_vlm_agree"
            fused.reasons.append("OCR 与视觉模型标准化后一致")
        elif has_ocr:
            fused.final_source = "ocr_base"
        elif has_vlm:
            fused.final_source = "vlm"
        else:
            fused.final_source = best_group[0].source

        # 低 OCR 置信度惩罚
        ocr_candidates = [c for c in best_group if c.source.startswith("ocr")]
        if ocr_candidates and max(c.confidence for c in ocr_candidates) < self.low_ocr_threshold:
            base_conf -= self.low_ocr_penalty
            fused.reasons.append("OCR 置信度偏低")

        # 历史别名加分
        if any(c.source.startswith("history") for c in best_group):
            base_conf = min(base_conf + 0.05, 0.98)
            fused.reasons.append("历史别名支持")

        # 存在不一致候选
        if len(groups) > 1:
            other_values = [k for k in groups if k != best_group_key]
            fused.reasons.append(f"存在不一致候选: {other_values}")
            if base_conf < self.auto_accept_threshold:
                fused.status = NEED_REVIEW
            else:
                fused.status = AUTO_ACCEPT
        else:
            if base_conf >= self.auto_accept_threshold:
                fused.status = AUTO_ACCEPT
            elif base_conf >= self.review_threshold:
                fused.status = NEED_REVIEW
            else:
                fused.status = NEED_REVIEW

        fused.final_value = best_group[0].value
        fused.final_confidence = round(max(0, min(base_conf, 0.99)), 4)
        return fused

    def _fuse_numeric(self, fused: FusedField) -> FusedField:
        """数字字段融合：严格冲突检测。"""
        candidates = fused.raw_candidates

        # 提取 OCR 和 VLM 候选
        ocr_candidates = [c for c in candidates if c.source.startswith("ocr")]
        vlm_candidates = [c for c in candidates if c.source == "vlm"]
        history_candidates = [c for c in candidates if c.source.startswith("history")]

        ocr_val = ocr_candidates[0].value if ocr_candidates else ""
        vlm_val = vlm_candidates[0].value if vlm_candidates else ""

        # 数字冲突检测
        if ocr_val and vlm_val:
            if self._numeric_equal(ocr_val, vlm_val):
                # 一致
                base_conf = max(
                    ocr_candidates[0].confidence if ocr_candidates else 0,
                    vlm_candidates[0].confidence if vlm_candidates else 0,
                )
                fused.final_value = ocr_val
                fused.final_confidence = round(min(base_conf + self.numeric_agree_bonus, 0.98), 4)
                fused.final_source = "ocr_vlm_agree"
                fused.status = AUTO_ACCEPT
                fused.reasons.append("OCR 与视觉模型数值完全一致")
            else:
                # 冲突！数字不一致必须标记
                fused.final_value = ocr_val  # 暂定 OCR
                fused.final_confidence = round(max(
                    ocr_candidates[0].confidence if ocr_candidates else 0,
                    vlm_candidates[0].confidence if vlm_candidates else 0,
                ) * 0.6, 4)
                fused.final_source = "conflict"
                fused.status = CONFLICT
                fused.reasons.append(f"数字冲突: OCR={ocr_val}, VLM={vlm_val}")
                # 即使历史支持某一方，也不能自动通过
                if history_candidates:
                    fused.reasons.append(
                        f"历史候选={history_candidates[0].value}（仅供参考，不自动采用）"
                    )
        elif ocr_val:
            fused.final_value = ocr_val
            fused.final_confidence = round(ocr_candidates[0].confidence * 0.85, 4)
            fused.final_source = "ocr_only"
            fused.status = NEED_REVIEW if ocr_candidates[0].confidence < self.auto_accept_threshold else AUTO_ACCEPT
            fused.reasons.append("仅 OCR 来源")
        elif vlm_val:
            fused.final_value = vlm_val
            fused.final_confidence = round(vlm_candidates[0].confidence * 0.85, 4)
            fused.final_source = "vlm_only"
            fused.status = NEED_REVIEW
            fused.reasons.append("仅视觉模型来源")
        elif history_candidates:
            fused.final_value = history_candidates[0].value
            fused.final_confidence = round(history_candidates[0].confidence * 0.6, 4)
            fused.final_source = "history_only"
            fused.status = NEED_REVIEW
            fused.reasons.append("仅历史候选（图片未识别到）")
        else:
            fused.status = EMPTY
            fused.reasons.append("无候选")

        return fused

    def _fuse_model_code(self, fused: FusedField) -> FusedField:
        """型号字段融合。"""
        # 型号基本逻辑与文字类似，但数字部分严格
        candidates = fused.raw_candidates
        ocr_candidates = [c for c in candidates if c.source.startswith("ocr")]
        vlm_candidates = [c for c in candidates if c.source == "vlm"]

        ocr_val = ocr_candidates[0].value if ocr_candidates else ""
        vlm_val = vlm_candidates[0].value if vlm_candidates else ""

        if ocr_val and vlm_val:
            # 大小写标准化比较
            if ocr_val.upper() == vlm_val.upper():
                fused.final_value = ocr_val
                fused.final_confidence = round(min(
                    max(ocr_candidates[0].confidence, vlm_candidates[0].confidence) + 0.10, 0.98
                ), 4)
                fused.final_source = "ocr_vlm_agree"
                fused.status = AUTO_ACCEPT
                fused.reasons.append("型号一致（忽略大小写）")
            else:
                # 检查是否只有数字不同
                if self._digit_difference(ocr_val, vlm_val):
                    fused.status = CONFLICT
                    fused.final_value = ocr_val
                    fused.final_source = "conflict"
                    fused.final_confidence = 0.5
                    fused.reasons.append(f"型号数字冲突: OCR={ocr_val}, VLM={vlm_val}")
                else:
                    fused.status = NEED_REVIEW
                    fused.final_value = ocr_val
                    fused.final_source = "ocr_base"
                    fused.final_confidence = round(ocr_candidates[0].confidence * 0.8, 4)
                    fused.reasons.append(f"型号不一致: OCR={ocr_val}, VLM={vlm_val}")
        elif ocr_val:
            fused.final_value = ocr_val
            fused.final_confidence = round(ocr_candidates[0].confidence * 0.85, 4)
            fused.final_source = "ocr_only"
            fused.status = AUTO_ACCEPT if ocr_candidates[0].confidence >= self.auto_accept_threshold else NEED_REVIEW
        elif vlm_val:
            fused.final_value = vlm_val
            fused.final_confidence = round(vlm_candidates[0].confidence * 0.85, 4)
            fused.final_source = "vlm_only"
            fused.status = NEED_REVIEW
        else:
            fused.status = EMPTY

        return fused

    def _fuse_date(self, fused: FusedField) -> FusedField:
        """日期字段：保留原样。"""
        candidates = fused.raw_candidates
        if not candidates:
            fused.status = EMPTY
            return fused

        # 优先 OCR
        ocr_candidates = [c for c in candidates if c.source.startswith("ocr")]
        if ocr_candidates:
            fused.final_value = ocr_candidates[0].value
            fused.final_confidence = round(ocr_candidates[0].confidence, 4)
            fused.final_source = "ocr_base"
        else:
            fused.final_value = candidates[0].value
            fused.final_confidence = round(candidates[0].confidence, 4)
            fused.final_source = candidates[0].source

        fused.status = AUTO_ACCEPT if fused.final_confidence >= self.auto_accept_threshold else NEED_REVIEW
        return fused

    @staticmethod
    def _numeric_equal(a: str, b: str) -> bool:
        """判断两个数字字符串是否等价。"""
        # 去除空格
        a_clean = a.strip().replace(" ", "")
        b_clean = b.strip().replace(" ", "")
        if a_clean == b_clean:
            return True
        # 尝试数值比较
        try:
            return float(a_clean) == float(b_clean)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _digit_difference(a: str, b: str) -> bool:
        """检查两个型号是否只有数字部分不同。"""
        a_digits = re.sub(r"[^0-9]", "", a)
        b_digits = re.sub(r"[^0-9]", "", b)
        a_letters = re.sub(r"[0-9]", "", a).upper()
        b_letters = re.sub(r"[0-9]", "", b).upper()
        return a_letters == b_letters and a_digits != b_digits
