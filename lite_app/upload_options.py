"""Validated upload options with backward-compatible per-image rotation."""

from __future__ import annotations

import json
from typing import Any

VALID_ROTATIONS = {"auto", "0", "90cw", "90ccw", "180"}


def normalize_rotations(raw: str, *, count: int, fallback: str) -> list[str]:
    """Return one validated rotation per uploaded image."""
    if fallback not in VALID_ROTATIONS:
        raise ValueError(f"无效的默认旋转设置: {fallback}")
    try:
        values: Any = json.loads(raw) if raw.strip() else [fallback] * count
    except json.JSONDecodeError as exc:
        raise ValueError("旋转设置不是有效JSON") from exc
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("旋转设置与图片数量不一致")
    normalized = [str(value) for value in values]
    if any(value not in VALID_ROTATIONS for value in normalized):
        raise ValueError("旋转设置包含无效值")
    return normalized


def rotation_for_image(job: dict[str, Any], one_based_index: int) -> str:
    """Resolve an image rotation while preserving old single-rotation jobs."""
    rotations = job.get("rotations")
    if isinstance(rotations, list) and 0 < one_based_index <= len(rotations):
        candidate = str(rotations[one_based_index - 1])
        if candidate in VALID_ROTATIONS:
            return candidate
    fallback = str(job.get("rotation", "auto"))
    return fallback if fallback in VALID_ROTATIONS else "auto"
