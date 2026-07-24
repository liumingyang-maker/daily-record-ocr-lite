"""布局几何算法：行聚类、横向配对、记录分组。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..ocr.base import OCRToken

logger = logging.getLogger(__name__)


class LayoutError(RuntimeError):
    """Local layout evidence cannot be generated safely."""


@dataclass
class TextLine:
    """聚类后的文本行。"""
    index: int
    tokens: list[OCRToken] = field(default_factory=list)
    bbox: list[float] = field(default_factory=lambda: [0, 0, 0, 0])
    center_y: float = 0.0
    text: str = ""

    def compute(self) -> None:
        if not self.tokens:
            return
        xs_min = min(t.bbox[0] for t in self.tokens)
        ys_min = min(t.bbox[1] for t in self.tokens)
        xs_max = max(t.bbox[2] for t in self.tokens)
        ys_max = max(t.bbox[3] for t in self.tokens)
        self.bbox = [xs_min, ys_min, xs_max, ys_max]
        self.center_y = (ys_min + ys_max) / 2
        # 行内按 x 排序
        self.tokens.sort(key=lambda t: t.center_x)
        self.text = " ".join(t.text for t in self.tokens)


@dataclass
class MaterialAmountPair:
    """原料-数量配对。"""
    name_token: OCRToken
    amount_token: OCRToken | None = None
    unit_token: OCRToken | None = None
    distance: float = 0.0


def cluster_lines(tokens: list[OCRToken], page_height: int) -> list[TextLine]:
    """
    按 center_y 聚类为文本行。

    使用动态行阈值（基于平均字符框高度），不使用固定像素。
    """
    if not tokens:
        return []

    # 计算平均字符框高度
    heights = [t.bbox[3] - t.bbox[1] for t in tokens if t.bbox[3] > t.bbox[1]]
    avg_height = sum(heights) / len(heights) if heights else page_height * 0.03

    # 行阈值：平均字符高度的 0.6 倍
    line_threshold = avg_height * 0.6

    # 按 center_y 排序
    sorted_tokens = sorted(tokens, key=lambda t: t.center_y)

    lines: list[TextLine] = []
    current_line = TextLine(index=0, tokens=[sorted_tokens[0]])
    current_center_y = sorted_tokens[0].center_y

    for token in sorted_tokens[1:]:
        if abs(token.center_y - current_center_y) <= line_threshold:
            current_line.tokens.append(token)
            # 更新当前行的平均 center_y
            current_center_y = sum(t.center_y for t in current_line.tokens) / len(current_line.tokens)
        else:
            current_line.compute()
            lines.append(current_line)
            current_line = TextLine(index=len(lines), tokens=[token])
            current_center_y = token.center_y

    current_line.compute()
    lines.append(current_line)

    # 重新编号
    for i, line in enumerate(lines):
        line.index = i

    return lines


def pair_materials_amounts(
    name_line: TextLine,
    amount_line: TextLine,
    max_x_offset_ratio: float = 0.5,
) -> list[MaterialAmountPair]:
    """
    将原料名称行与下方数量行按横向位置配对。

    规则：
    - 数量 token 的中心 x 应落在原料 bbox 水平范围附近
    - 允许少量偏移
    - 同一数量不能同时分配给两个原料
    - 使用最小距离贪心匹配
    """
    pairs: list[MaterialAmountPair] = []
    used_amounts: set[int] = set()

    name_tokens = name_line.tokens
    amount_tokens = amount_line.tokens

    for name_tok in name_tokens:
        name_width = name_tok.bbox[2] - name_tok.bbox[0]
        tolerance = name_width * max_x_offset_ratio

        best_amount: OCRToken | None = None
        best_dist = float("inf")
        best_idx = -1

        for idx, amt_tok in enumerate(amount_tokens):
            if idx in used_amounts:
                continue
            # 计算水平距离
            dist = abs(amt_tok.center_x - name_tok.center_x)
            if dist <= tolerance + name_width * 0.3 and dist < best_dist:
                best_dist = dist
                best_amount = amt_tok
                best_idx = idx

        if best_amount is not None:
            used_amounts.add(best_idx)
            pairs.append(MaterialAmountPair(
                name_token=name_tok,
                amount_token=best_amount,
                distance=best_dist,
            ))
        else:
            pairs.append(MaterialAmountPair(
                name_token=name_tok,
                amount_token=None,
                distance=0,
            ))

    return pairs


def detect_record_boundaries(
    lines: list[TextLine],
    page_height: int,
    vlm_record_bboxes: list[list[float]] | None = None,
) -> list[dict[str, Any]]:
    """
    检测记录分组边界。

    证据：日期、标题、大段垂直空白、VLM record_bbox。
    """
    if not lines:
        return []

    # 如果 VLM 给出了 record_bbox，优先使用
    if vlm_record_bboxes:
        records = []
        for i, bbox in enumerate(vlm_record_bboxes):
            records.append({
                "record_index": i,
                "bbox": bbox,
                "source": "vlm",
            })
        return records

    # 本地检测：基于垂直空白
    records: list[dict[str, Any]] = []
    current_start = 0
    avg_line_height = (
        sum(line.bbox[3] - line.bbox[1] for line in lines) / len(lines)
        if lines
        else 20
    )

    gap_threshold = avg_line_height * 3  # 3倍行高以上视为分隔

    for i in range(1, len(lines)):
        prev_bottom = lines[i - 1].bbox[3]
        curr_top = lines[i].bbox[1]
        gap = curr_top - prev_bottom

        if gap > gap_threshold:
            # 发现分隔
            records.append({
                "record_index": len(records),
                "line_range": [current_start, i - 1],
                "bbox": _lines_bbox(lines[current_start:i]),
                "source": "local_gap",
            })
            current_start = i

    # 最后一段
    records.append({
        "record_index": len(records),
        "line_range": [current_start, len(lines) - 1],
        "bbox": _lines_bbox(lines[current_start:]),
        "source": "local_gap",
    })

    return records


def _lines_bbox(lines: list[TextLine]) -> list[float]:
    """计算多行的包围盒。"""
    if not lines:
        return [0, 0, 0, 0]
    x_min = min(line.bbox[0] for line in lines)
    y_min = min(line.bbox[1] for line in lines)
    x_max = max(line.bbox[2] for line in lines)
    y_max = max(line.bbox[3] for line in lines)
    return [x_min, y_min, x_max, y_max]


def build_layout_evidence(tokens: list[OCRToken], page_height: int) -> dict[str, Any]:
    """Run the geometry defense immediately after OCR and serialize its evidence."""
    lines = cluster_lines(tokens, page_height)
    pairs: list[dict[str, Any]] = []
    for index in range(len(lines) - 1):
        name_line = lines[index]
        amount_line = lines[index + 1]
        if not name_line.tokens or not amount_line.tokens:
            continue
        numeric_count = sum(
            any(character.isdigit() for character in token.text)
            for token in amount_line.tokens
        )
        if numeric_count == 0:
            continue
        for pair in pair_materials_amounts(name_line, amount_line):
            if pair.amount_token is None:
                continue
            pairs.append(
                {
                    "name_token_ids": [pair.name_token.id],
                    "amount_token_ids": [pair.amount_token.id],
                    "name": pair.name_token.text,
                    "amount": pair.amount_token.text,
                    "distance": pair.distance,
                    "score": max(0.0, 1.0 - pair.distance / max(page_height, 1)),
                }
            )
    records = detect_record_boundaries(lines, page_height)
    return {
        "lines": [
            {
                "index": line.index,
                "token_ids": [token.id for token in line.tokens],
                "bbox": line.bbox,
                "text": line.text,
            }
            for line in lines
        ],
        "pairs": pairs,
        "records": records,
    }
