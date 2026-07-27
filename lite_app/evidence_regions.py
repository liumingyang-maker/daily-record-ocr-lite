"""Formula-level review evidence derived without changing recognition values."""

from __future__ import annotations

import hashlib
import io
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .image_utils_v2 import orient_image
from .ocr.base import OCRPage, OCRToken
from .storage import (
    RequiredDataError,
    read_json_optional,
    write_bytes_atomic,
    write_json_atomic,
)
from .upload_options import rotation_for_image

MIN_AREA = 0.005
MAX_AREA = 0.95


@dataclass(frozen=True, slots=True)
class ResolvedRegion:
    normalized_bbox: list[float]
    source: str


def validate_normalized_bbox(value: Any) -> list[float] | None:
    """Return a safe normalized rectangle or reject the entire value."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if not all(
        isinstance(item, (int, float)) and math.isfinite(float(item))
        for item in value
    ):
        return None
    x1, y1, x2, y2 = (float(item) for item in value)
    if not all(0.0 <= item <= 1.0 for item in (x1, y1, x2, y2)):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    area = (x2 - x1) * (y2 - y1)
    if area < MIN_AREA or area >= MAX_AREA:
        return None
    return [x1, y1, x2, y2]


def resolve_formula_region(
    model_bbox: Any,
    local_bbox: Any,
    *,
    content_bbox: Any = None,
    padding: float = 0.10,
) -> ResolvedRegion:
    """Fuse candidates, expanding on disagreement and failing open to full image."""
    model = validate_normalized_bbox(model_bbox)
    local = validate_normalized_bbox(local_bbox)
    if model and local:
        bbox = _union(model, local)
        source = "hybrid"
    elif model:
        bbox = model
        source = "model"
    elif local:
        bbox = local
        source = "local"
    else:
        content = validate_normalized_bbox(content_bbox)
        if content:
            bbox = content
            source = "local"
        else:
            return ResolvedRegion([0.0, 0.0, 1.0, 1.0], "full_image")
    return ResolvedRegion(_pad_and_clamp(bbox, padding), source)


def generate_formula_evidence(
    job_dir: Path,
    job: dict[str, Any],
    final: dict[str, Any],
    ocr_pages: list[OCRPage],
    layout_by_page: dict[str, Any],
    preprocess_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create review-only crops and an integrity-bound manifest."""
    root = job_dir.resolve()
    recognition_run_id = str(final.get("recognition_run_id", ""))
    if not recognition_run_id or recognition_run_id != str(
        job.get("recognition_run_id", "")
    ):
        raise ValueError("Formula evidence requires the current recognition run.")
    preprocess_config = preprocess_config or {}
    page_map = {page.image_index: page for page in ocr_pages}
    formulas_by_page = _formulas_by_page(final)
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "recognition_run_id": recognition_run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "formulas": {},
    }
    evidence_dir = root / "review" / "evidence"

    for image_index, formulas in formulas_by_page.items():
        page = page_map.get(image_index)
        source_path = _source_path(root, job, image_index)
        if page is None or source_path is None or not source_path.is_file():
            continue
        source_hash = _sha256(source_path)
        content_bbox = _content_bbox(page)
        model_bboxes = validate_page_model_bboxes(formulas)
        page_layout = layout_by_page.get(str(image_index), {})
        with Image.open(source_path) as opened:
            source_image = ImageOps.exif_transpose(opened).convert("RGB")
            source_image = orient_image(
                source_image,
                _evidence_rotation(job, image_index),
                auto_rotate=bool(preprocess_config.get("auto_rotate", True)),
            )
            width, height = source_image.size
            oriented_name = f"page_{image_index:03d}_oriented.jpg"
            oriented_path = evidence_dir / oriented_name
            oriented_buffer = io.BytesIO()
            source_image.save(
                oriented_buffer,
                format="JPEG",
                quality=94,
                optimize=True,
            )
            write_bytes_atomic(oriented_path, oriented_buffer.getvalue())
            oriented_hash = _sha256(oriented_path)
            for position, formula in enumerate(formulas, 1):
                formula_id = str(formula.get("formula_id", ""))
                if not formula_id:
                    continue
                local_bbox = _local_formula_bbox(
                    formula,
                    page,
                    position=position,
                    total=len(formulas),
                    content_bbox=content_bbox,
                    layout=page_layout,
                )
                resolved = resolve_formula_region(
                    model_bboxes.get(formula_id),
                    local_bbox,
                    content_bbox=content_bbox,
                )
                pixel_bbox = _pixel_bbox(resolved.normalized_bbox, width, height)
                crop = source_image.crop(tuple(pixel_bbox))
                buffer = io.BytesIO()
                crop.save(buffer, format="JPEG", quality=92, optimize=True)
                safe_name = _crop_filename(formula_id)
                crop_path = evidence_dir / safe_name
                write_bytes_atomic(crop_path, buffer.getvalue())
                manifest["formulas"][formula_id] = {
                    "formula_id": formula_id,
                    "recognition_run_id": recognition_run_id,
                    "source_order": _source_order(formula),
                    "source_image_index": image_index,
                    "source_path": source_path.relative_to(root).as_posix(),
                    "source_sha256": source_hash,
                    "oriented_source_path": oriented_path.relative_to(root).as_posix(),
                    "oriented_source_sha256": oriented_hash,
                    "normalized_bbox": [round(value, 6) for value in resolved.normalized_bbox],
                    "pixel_bbox": pixel_bbox,
                    "locator_source": resolved.source,
                    "crop_path": crop_path.relative_to(root).as_posix(),
                    "crop_sha256": _sha256(crop_path),
                    "crop_width": crop.width,
                    "crop_height": crop.height,
                }

    write_json_atomic(root / "review" / "evidence_regions.json", manifest)
    return manifest


def invalidate_formula_evidence(job_dir: Path, recognition_run_id: str) -> None:
    """Atomically make evidence from a previous recognition run unreachable."""
    write_json_atomic(
        job_dir.resolve() / "review" / "evidence_regions.json",
        {
            "schema_version": 2,
            "recognition_run_id": str(recognition_run_id),
            "generated_at": datetime.now(UTC).isoformat(),
            "formulas": {},
        },
    )


def verified_evidence_path(
    job_dir: Path,
    formula_id: str,
    *,
    job: dict[str, Any],
    final: dict[str, Any],
    kind: str = "crop",
    hash_cache: dict[Path, str] | None = None,
) -> Path | None:
    """Resolve one manifest-bound crop after source and crop integrity checks."""
    root = job_dir.resolve()
    try:
        manifest = read_json_optional(root / "review" / "evidence_regions.json")
    except RequiredDataError:
        return None
    if not isinstance(manifest, dict):
        return None
    if manifest.get("schema_version") != 2:
        return None
    recognition_run_id = str(final.get("recognition_run_id", ""))
    if (
        not recognition_run_id
        or recognition_run_id != str(job.get("recognition_run_id", ""))
        or recognition_run_id != str(manifest.get("recognition_run_id", ""))
    ):
        return None
    context = _formula_context(final, formula_id)
    if context is None:
        return None
    source_image_index, formula = context
    expected_source = _source_path(root, job, source_image_index)
    if expected_source is None:
        return None
    formulas = manifest.get("formulas")
    if not isinstance(formulas, dict):
        return None
    entry = formulas.get(str(formula_id))
    if not isinstance(entry, dict):
        return None
    if (
        str(entry.get("formula_id", "")) != str(formula_id)
        or str(entry.get("recognition_run_id", "")) != recognition_run_id
        or _safe_int(entry.get("source_image_index")) != source_image_index
        or _safe_int(entry.get("source_order")) != _source_order(formula)
        or str(entry.get("crop_path", ""))
        != f"review/evidence/{_crop_filename(formula_id)}"
        or str(entry.get("oriented_source_path", ""))
        != f"review/evidence/page_{source_image_index:03d}_oriented.jpg"
    ):
        return None
    source = _bounded_manifest_path(root, entry.get("source_path"), "source")
    crop = _bounded_manifest_path(root, entry.get("crop_path"), "review/evidence")
    oriented = _bounded_manifest_path(
        root,
        entry.get("oriented_source_path"),
        "review/evidence",
    )
    if (
        source is None
        or source != expected_source
        or crop is None
        or oriented is None
        or not source.is_file()
        or not crop.is_file()
        or not oriented.is_file()
    ):
        return None
    hash_cache = hash_cache if hash_cache is not None else {}
    if _sha256_cached(source, hash_cache) != str(entry.get("source_sha256", "")):
        return None
    if _sha256_cached(crop, hash_cache) != str(entry.get("crop_sha256", "")):
        return None
    if _sha256_cached(oriented, hash_cache) != str(
        entry.get("oriented_source_sha256", "")
    ):
        return None
    return oriented if kind == "full" else crop


def validate_page_model_bboxes(
    formulas: list[dict[str, Any]],
) -> dict[str, list[float] | None]:
    """Reject page-level bbox sets whose order or overlap is implausible."""
    ordered = sorted(formulas, key=_source_order)
    result = {
        str(formula.get("formula_id", "")): validate_normalized_bbox(
            formula.get("record_bbox")
        )
        for formula in ordered
    }
    invalid: set[str] = set()
    for index, left_formula in enumerate(ordered):
        left_id = str(left_formula.get("formula_id", ""))
        left = result.get(left_id)
        if left is None:
            continue
        for right_formula in ordered[index + 1 :]:
            right_id = str(right_formula.get("formula_id", ""))
            right = result.get(right_id)
            if right is None:
                continue
            if _intersection_ratio(left, right) >= 0.70:
                invalid.update((left_id, right_id))
                continue
            if (
                _horizontal_overlap_ratio(left, right) >= 0.50
                and _center_y(left) >= _center_y(right)
            ):
                invalid.update((left_id, right_id))
    for formula_id in invalid:
        result[formula_id] = None
    return result


def _formulas_by_page(final: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for page in final.get("pages", []):
        image_index = int(page.get("source_image_index", 1))
        formulas = result.setdefault(image_index, [])
        for section in page.get("product_sections", []):
            formulas.extend(section.get("formulas", []))
    for formulas in result.values():
        formulas.sort(key=_source_order)
    return result


def _source_path(root: Path, job: dict[str, Any], image_index: int) -> Path | None:
    images = job.get("images", [])
    if image_index < 1 or image_index > len(images):
        return None
    relative = str(images[image_index - 1].get("source", ""))
    if not relative:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _evidence_rotation(job: dict[str, Any], image_index: int) -> str:
    images = job.get("images", [])
    if 0 < image_index <= len(images):
        stored = str(images[image_index - 1].get("rotation", ""))
        if stored in {"auto", "0", "90cw", "90ccw", "180"}:
            return stored
    return rotation_for_image(job, image_index)


def _bounded_manifest_path(root: Path, value: Any, prefix: str) -> Path | None:
    relative = str(value or "").replace("\\", "/")
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        return None
    expected = f"{prefix.rstrip('/')}/"
    if not relative.startswith(expected):
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _content_bbox(page: OCRPage) -> list[float] | None:
    if not page.tokens or not page.width or not page.height:
        return None
    bbox = _tokens_bbox(page.tokens, page)
    return _pad_and_clamp(bbox, 0.04)


def _local_formula_bbox(
    formula: dict[str, Any],
    page: OCRPage,
    *,
    position: int,
    total: int,
    content_bbox: list[float] | None,
    layout: dict[str, Any],
) -> list[float] | None:
    slot_bbox = _layout_record_bbox(layout, page, position, total)
    slot_height = 0.0
    if slot_bbox:
        slot_height = slot_bbox[3] - slot_bbox[1]
    elif content_bbox and total > 0:
        x1, y1, x2, y2 = content_bbox
        slot_height = (y2 - y1) / total
        slot_bbox = [
            x1,
            y1 + slot_height * (position - 1),
            x2,
            y1 + slot_height * position,
        ]
    primary_values = [
        str(formula.get("formula_no", "")),
        str(formula.get("record_date", {}).get("value", "")),
    ]
    secondary_values = [
        str(field.get("value", ""))
        for material in formula.get("materials", [])
        for field in (material.get("name", {}), material.get("amount", {}))
    ]
    secondary_values.extend(
        str(field.get("value", ""))
        for parameter in formula.get("process_parameters", [])
        for field in (parameter.get("name", {}), parameter.get("value", {}))
    )
    primary = _matching_primary_tokens(page.tokens, primary_values)
    layout_anchor = _matching_layout_lines(layout, primary_values, page)
    if primary:
        anchor = _tokens_bbox(primary, page)
        if slot_bbox and _bbox_center_distance_y(anchor, slot_bbox) > slot_height * 1.2:
            return slot_bbox
        selected = list(primary)
        for value in secondary_values:
            matches = _matching_tokens(page.tokens, [value])
            if matches:
                selected.append(min(matches, key=lambda token: _distance(token, anchor, page)))
        candidate = _tokens_bbox(selected, page)
        if slot_bbox and candidate[3] - candidate[1] > slot_height * 1.75:
            return slot_bbox
        if layout_anchor:
            candidate = _union(candidate, layout_anchor)
        return _union(candidate, slot_bbox) if slot_bbox else candidate

    if layout_anchor:
        return _union(layout_anchor, slot_bbox) if slot_bbox else layout_anchor

    return slot_bbox


def _layout_record_bbox(
    layout: dict[str, Any], page: OCRPage, position: int, total: int
) -> list[float] | None:
    records = layout.get("records", []) if isinstance(layout, dict) else []
    if (
        not isinstance(records, list)
        or len(records) != total
        or not (0 < position <= len(records))
    ):
        return None
    record = records[position - 1]
    if not isinstance(record, dict):
        return None
    return _pixel_layout_bbox(record.get("bbox"), page)


def _matching_layout_lines(
    layout: dict[str, Any], values: list[str], page: OCRPage
) -> list[float] | None:
    anchors = [value for value in values if str(value).strip()]
    if not anchors or not isinstance(layout, dict):
        return None
    matches: list[list[float]] = []
    for line in layout.get("lines", []):
        if not isinstance(line, dict):
            continue
        text = str(line.get("text", ""))
        if any(_layout_line_matches(text, anchor) for anchor in anchors):
            bbox = _pixel_layout_bbox(line.get("bbox"), page)
            if bbox:
                matches.append(bbox)
    if not matches:
        return None
    result = matches[0]
    for match in matches[1:]:
        result = _union(result, match)
    return result


def _matching_primary_tokens(
    tokens: list[OCRToken], values: list[str]
) -> list[OCRToken]:
    anchors = [value for value in values if str(value).strip()]
    return [
        token
        for token in tokens
        if any(_token_matches_primary(token.text, anchor) for anchor in anchors)
    ]


def _token_matches_primary(text: str, anchor: str) -> bool:
    raw_anchor = str(anchor).strip()
    raw_text = str(text).strip()
    if _has_circled_number(raw_anchor):
        return raw_text.startswith(raw_anchor)
    normalized_anchor = _normalize(raw_anchor)
    return len(normalized_anchor) >= 3 and _normalize(raw_text) == normalized_anchor


def _layout_line_matches(text: str, anchor: str) -> bool:
    raw_anchor = str(anchor).strip()
    raw_text = str(text).strip()
    if _has_circled_number(raw_anchor):
        return raw_anchor in raw_text
    normalized_anchor = _normalize(raw_anchor)
    return len(normalized_anchor) >= 3 and normalized_anchor in _normalize(raw_text)


def _has_circled_number(value: str) -> bool:
    return any("①" <= character <= "⑳" for character in value)


def _pixel_layout_bbox(value: Any, page: OCRPage) -> list[float] | None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or not page.width
        or not page.height
    ):
        return None
    try:
        normalized = [
            float(value[0]) / page.width,
            float(value[1]) / page.height,
            float(value[2]) / page.width,
            float(value[3]) / page.height,
        ]
    except (TypeError, ValueError):
        return None
    return validate_normalized_bbox(normalized)


def _formula_context(
    final: dict[str, Any], formula_id: str
) -> tuple[int, dict[str, Any]] | None:
    for page in final.get("pages", []):
        image_index = int(page.get("source_image_index", 1))
        for section in page.get("product_sections", []):
            for formula in section.get("formulas", []):
                if str(formula.get("formula_id", "")) == str(formula_id):
                    return image_index, formula
    return None


def _source_order(formula: dict[str, Any]) -> int:
    value = formula.get("source_order", formula.get("formula_sequence", 0))
    return _safe_int(value) or 0


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _crop_filename(formula_id: str) -> str:
    digest = hashlib.sha256(str(formula_id).encode()).hexdigest()[:20]
    return f"formula_{digest}.jpg"


def _center_y(bbox: list[float]) -> float:
    return (bbox[1] + bbox[3]) / 2


def _intersection_ratio(left: list[float], right: list[float]) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = width * height
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / max(min(left_area, right_area), 1e-9)


def _horizontal_overlap_ratio(left: list[float], right: list[float]) -> float:
    overlap = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    return overlap / max(min(left[2] - left[0], right[2] - right[0]), 1e-9)


def _matching_tokens(tokens: list[OCRToken], values: list[str]) -> list[OCRToken]:
    normalized = {_normalize(value) for value in values if _normalize(value)}
    if not normalized:
        return []
    return [token for token in tokens if _normalize(token.text) in normalized]


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"\s+", "", text).strip()


def _tokens_bbox(tokens: list[OCRToken], page: OCRPage) -> list[float]:
    return [
        min(token.bbox[0] for token in tokens) / page.width,
        min(token.bbox[1] for token in tokens) / page.height,
        max(token.bbox[2] for token in tokens) / page.width,
        max(token.bbox[3] for token in tokens) / page.height,
    ]


def _distance(token: OCRToken, bbox: list[float], page: OCRPage) -> float:
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return math.hypot(token.center_x / page.width - center_x, token.center_y / page.height - center_y)


def _union(left: list[float], right: list[float]) -> list[float]:
    return [
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    ]


def _bbox_center_distance_y(left: list[float], right: list[float]) -> float:
    return abs((left[1] + left[3]) / 2 - (right[1] + right[3]) / 2)


def _pad_and_clamp(bbox: list[float], padding: float) -> list[float]:
    x1, y1, x2, y2 = bbox
    pad_x = max(0.02, (x2 - x1) * max(0.0, padding)) if padding else 0.0
    pad_y = max(0.02, (y2 - y1) * max(0.0, padding)) if padding else 0.0
    return [
        max(0.0, x1 - pad_x),
        max(0.0, y1 - pad_y),
        min(1.0, x2 + pad_x),
        min(1.0, y2 + pad_y),
    ]


def _pixel_bbox(bbox: list[float], width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = bbox
    return [
        max(0, min(width - 1, math.floor(x1 * width))),
        max(0, min(height - 1, math.floor(y1 * height))),
        max(1, min(width, math.ceil(x2 * width))),
        max(1, min(height, math.ceil(y2 * height))),
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_cached(path: Path, cache: dict[Path, str]) -> str:
    resolved = path.resolve()
    if resolved not in cache:
        cache[resolved] = _sha256(resolved)
    return cache[resolved]
