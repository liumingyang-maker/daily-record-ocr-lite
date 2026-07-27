"""Associate structured fields with page-scoped OCR and layout evidence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from ..ocr.base import OCRPage, OCRToken


class AssociationError(RuntimeError):
    """OCR evidence cannot be associated without violating its contract."""


@dataclass
class FieldEvidence:
    field_id: str
    field_type: str
    source_image_index: int
    field_bbox: list[float] | None
    record_bbox: list[float] | None
    evidence_token_ids: list[str]
    vlm_value: str
    anchor_token_ids: list[str] = field(default_factory=list)
    anchor_bbox: list[float] | None = None
    anchor_value: str = ""


@dataclass
class AssociatedOCRCandidate:
    value: str
    token_ids: list[str]
    bbox: list[float] | None
    confidence: float
    method: str
    association_score: float
    reasons: list[str] = field(default_factory=list)
    requires_review: bool = False


LayoutEvidence = dict[str, Any]


def record_boundary_mismatch(
    source_image_index: int,
    record_bbox: list[float] | None,
    pages: list[OCRPage],
    layout: LayoutEvidence | None,
) -> bool:
    if not record_bbox or not layout:
        return False
    page = next(
        (item for item in pages if item.image_index == source_image_index),
        None,
    )
    if page is None:
        return False
    records = layout.get("records", {}).get(str(source_image_index), [])
    boxes = [
        _normalize_layout_bbox(record.get("bbox"), page)
        for record in records
        if _valid_bbox(record.get("bbox"))
    ]
    return bool(boxes) and max(_overlap_ratio(record_bbox, box) for box in boxes) < 0.3


def associate_field(
    field: FieldEvidence,
    pages: list[OCRPage],
    layout: LayoutEvidence | None,
) -> list[AssociatedOCRCandidate]:
    page = next(
        (item for item in pages if item.image_index == field.source_image_index),
        None,
    )
    if page is None:
        return []
    by_id = {token.id: token for token in page.tokens}
    numeric_field = field.field_type in {"amount", "numeric"}

    direct = [by_id[token_id] for token_id in field.evidence_token_ids if token_id in by_id]
    if direct and (
        not numeric_field
        or _tokens_within_region(direct, page, field.record_bbox)
    ):
        return [
            _candidate(
                direct,
                page,
                "evidence_token_ids",
                1.0,
                ["视觉模型显式引用页内 OCR token"],
            )
        ]

    if field.field_bbox:
        overlaps = []
        for token in page.tokens:
            if numeric_field and not _tokens_within_region(
                [token], page, field.record_bbox
            ):
                continue
            normalized = _normalize_bbox(token.bbox, page)
            iou = _iou(field.field_bbox, normalized)
            if iou >= 0.05:
                overlaps.append((token, iou))
        if overlaps:
            seed = max(overlaps, key=lambda item: item[1])[0]
            tokens = _adjacent_tokens(seed, page.tokens, field.field_bbox, page)
            if numeric_field:
                tokens = [
                    token
                    for token in tokens
                    if _tokens_within_region([token], page, field.record_bbox)
                ]
            return [
                _candidate(
                    tokens,
                    page,
                    "bbox_iou",
                    max(value for _, value in overlaps),
                    ["字段 bbox 与 OCR bbox 相交"],
                )
            ]

        field_center = _center(field.field_bbox)
        distances: list[tuple[OCRToken, float]] = []
        for token in page.tokens:
            if numeric_field and not _tokens_within_region(
                [token], page, field.record_bbox
            ):
                continue
            token_center = _center(_normalize_bbox(token.bbox, page))
            distance = math.dist(field_center, token_center)
            if distance <= 0.05:
                distances.append((token, distance))
        if distances:
            seed, distance = min(distances, key=lambda item: item[1])
            tokens = _adjacent_tokens(seed, page.tokens, field.field_bbox, page)
            if numeric_field:
                tokens = [
                    token
                    for token in tokens
                    if _tokens_within_region([token], page, field.record_bbox)
                ]
            return [
                _candidate(
                    tokens,
                    page,
                    "center_distance",
                    max(0.0, 1.0 - distance / 0.05),
                    ["中心距离在页面尺寸 5% 以内，独立于 IoU 判定"],
                )
            ]

    layout_candidate = _from_layout(field, page, layout)
    if layout_candidate is not None:
        return [layout_candidate]

    if field.vlm_value and field.field_type not in {"amount", "numeric"}:
        exact = [token for token in page.tokens if token.text == field.vlm_value]
        if exact:
            return [
                _candidate(
                    [exact[0]],
                    page,
                    "exact_text_fallback",
                    0.4,
                    ["非数字字段精确文本回退"],
                )
            ]
    return []


def _from_layout(
    field: FieldEvidence,
    page: OCRPage,
    layout: LayoutEvidence | None,
) -> AssociatedOCRCandidate | None:
    if not layout or field.field_type not in {"amount", "numeric"}:
        return None
    pairs = layout.get("pairs", {}).get(str(field.source_image_index), [])
    records = layout.get("records", {}).get(str(field.source_image_index), [])
    local_record: list[float] | None = None
    boundary_mismatch = False
    if field.record_bbox and records:
        scored_records = [
            (
                _overlap_ratio(
                    field.record_bbox,
                    _normalize_layout_bbox(record.get("bbox"), page),
                ),
                _normalize_layout_bbox(record.get("bbox"), page),
            )
            for record in records
            if _valid_bbox(record.get("bbox"))
        ]
        if scored_records:
            record_score, local_record = max(scored_records, key=lambda item: item[0])
            boundary_mismatch = record_score < 0.3

    tokens_by_id = {token.id: token for token in page.tokens}
    candidates: list[tuple[float, dict[str, Any], list[OCRToken]]] = []
    for pair in pairs:
        amount_ids = pair.get("amount_token_ids", [])
        if not amount_ids:
            continue
        tokens = [tokens_by_id[token_id] for token_id in amount_ids if token_id in tokens_by_id]
        if not tokens:
            continue
        pair_center = _center(_normalize_bbox(tokens[0].bbox, page))
        active_record = field.record_bbox or local_record
        if active_record and not _contains(active_record, pair_center):
            continue
        if not _tokens_within_region(tokens, page, active_record):
            continue

        score = float(pair.get("score", 0.65))
        name_ids = set(pair.get("name_token_ids", []))
        token_anchor = bool(
            field.anchor_token_ids and name_ids.intersection(field.anchor_token_ids)
        )
        if token_anchor:
            score += 1.0
        pair_name = _normalize_text(str(pair.get("name", "")))
        text_anchor = bool(
            field.anchor_value
            and pair_name
            and pair_name == _normalize_text(field.anchor_value)
        )
        if text_anchor:
            score += 0.8
        name_bbox: list[float] | None = None
        if field.anchor_bbox and name_ids:
            name_tokens = [
                tokens_by_id[token_id]
                for token_id in name_ids
                if token_id in tokens_by_id
            ]
            if name_tokens:
                name_bbox = _candidate(
                    name_tokens, page, "anchor", 0.0, []
                ).bbox
                if name_bbox:
                    score += _iou(field.anchor_bbox, name_bbox)
        bbox_anchor = bool(
            field.anchor_bbox
            and name_bbox
            and _iou(field.anchor_bbox, name_bbox) >= 0.05
        )
        if not (token_anchor or text_anchor or bbox_anchor):
            continue
        candidates.append((score, pair, tokens))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.15:
        return None
    score, _, tokens = candidates[0]
    reasons = ["本地 material-amount 布局配对（记录边界与材料锚点）"]
    if boundary_mismatch:
        reasons.append("RECORD_BOUNDARY_MISMATCH")
    candidate = _candidate(
        tokens,
        page,
        "layout_pair",
        min(score, 1.0),
        reasons,
    )
    candidate.requires_review = boundary_mismatch
    return candidate


def _tokens_within_region(
    tokens: list[OCRToken],
    page: OCRPage,
    region: list[float] | None,
) -> bool:
    if not tokens or not region:
        return False
    return all(
        _contains_bbox(region, _normalize_bbox(token.bbox, page))
        for token in tokens
    )


def _contains_bbox(container: list[float], value: list[float]) -> bool:
    return (
        container[0] <= value[0]
        and container[1] <= value[1]
        and value[2] <= container[2]
        and value[3] <= container[3]
    )


def _adjacent_tokens(
    seed: OCRToken,
    tokens: list[OCRToken],
    field_bbox: list[float],
    page: OCRPage,
) -> list[OCRToken]:
    normalized_seed = _normalize_bbox(seed.bbox, page)
    seed_height = max(normalized_seed[3] - normalized_seed[1], 0.001)
    candidates = []
    for token in tokens:
        bbox = _normalize_bbox(token.bbox, page)
        vertical_distance = abs(_center(bbox)[1] - _center(normalized_seed)[1])
        horizontal_gap = max(
            bbox[0] - normalized_seed[2],
            normalized_seed[0] - bbox[2],
            0.0,
        )
        intersects_field = _iou(field_bbox, bbox) > 0
        if vertical_distance <= seed_height * 0.7 and (
            intersects_field or horizontal_gap <= max(seed_height, 0.02)
        ):
            candidates.append(token)
    candidates.sort(key=lambda token: token.center_x)
    return candidates or [seed]


def _candidate(
    tokens: list[OCRToken],
    page: OCRPage,
    method: str,
    score: float,
    reasons: list[str],
) -> AssociatedOCRCandidate:
    ordered = sorted({token.id: token for token in tokens}.values(), key=lambda token: token.center_x)
    normalized_boxes = [_normalize_bbox(token.bbox, page) for token in ordered]
    bbox = [
        min(box[0] for box in normalized_boxes),
        min(box[1] for box in normalized_boxes),
        max(box[2] for box in normalized_boxes),
        max(box[3] for box in normalized_boxes),
    ]
    return AssociatedOCRCandidate(
        value=_join_tokens([token.text for token in ordered]),
        token_ids=[token.id for token in ordered],
        bbox=bbox,
        confidence=sum(token.confidence for token in ordered) / len(ordered),
        method=method,
        association_score=round(score, 4),
        reasons=reasons,
    )


def _join_tokens(parts: list[str]) -> str:
    if not parts:
        return ""
    if all(re.fullmatch(r"[+\-.\d%]+", part or "") for part in parts):
        return "".join(parts)
    if all(re.fullmatch(r"[\w\u3400-\u9fff+\-./%]+", part or "") for part in parts):
        return "".join(parts)
    return " ".join(parts)


def _normalize_bbox(bbox: list[float], page: OCRPage) -> list[float]:
    if page.width <= 0 or page.height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        bbox[0] / page.width,
        bbox[1] / page.height,
        bbox[2] / page.width,
        bbox[3] / page.height,
    ]


def _center(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _normalize_layout_bbox(bbox: Any, page: OCRPage) -> list[float]:
    if not _valid_bbox(bbox):
        return [0.0, 0.0, 0.0, 0.0]
    values = [float(value) for value in bbox]
    if max(values) <= 1.0:
        return values
    return [
        values[0] / page.width,
        values[1] / page.height,
        values[2] / page.width,
        values[3] / page.height,
    ]


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
    )


def _contains(bbox: list[float], point: tuple[float, float]) -> bool:
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = (x2 - x1) * (y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = (x2 - x1) * (y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    smaller = min(area_a, area_b)
    return intersection / smaller if smaller else 0.0
