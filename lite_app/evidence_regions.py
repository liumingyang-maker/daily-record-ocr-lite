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

from .ocr.base import OCRPage, OCRToken
from .storage import read_json_optional, write_bytes_atomic, write_json_atomic

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
) -> dict[str, Any]:
    """Create review-only crops and an integrity-bound manifest."""
    del layout_by_page  # OCR anchors are more precise than current coarse records.
    root = job_dir.resolve()
    page_map = {page.image_index: page for page in ocr_pages}
    formulas_by_page = _formulas_by_page(final)
    manifest: dict[str, Any] = {
        "schema_version": 1,
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
        with Image.open(source_path) as opened:
            source_image = ImageOps.exif_transpose(opened).convert("RGB")
            width, height = source_image.size
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
                )
                resolved = resolve_formula_region(
                    formula.get("record_bbox"),
                    local_bbox,
                    content_bbox=content_bbox,
                )
                pixel_bbox = _pixel_bbox(resolved.normalized_bbox, width, height)
                crop = source_image.crop(tuple(pixel_bbox))
                buffer = io.BytesIO()
                crop.save(buffer, format="JPEG", quality=92, optimize=True)
                safe_name = f"formula_{hashlib.sha256(formula_id.encode()).hexdigest()[:20]}.jpg"
                crop_path = evidence_dir / safe_name
                write_bytes_atomic(crop_path, buffer.getvalue())
                manifest["formulas"][formula_id] = {
                    "source_image_index": image_index,
                    "source_path": source_path.relative_to(root).as_posix(),
                    "source_sha256": source_hash,
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


def verified_evidence_path(job_dir: Path, formula_id: str) -> Path | None:
    """Resolve one manifest-bound crop after source and crop integrity checks."""
    root = job_dir.resolve()
    manifest = read_json_optional(root / "review" / "evidence_regions.json")
    if not isinstance(manifest, dict):
        return None
    formulas = manifest.get("formulas")
    if not isinstance(formulas, dict):
        return None
    entry = formulas.get(str(formula_id))
    if not isinstance(entry, dict):
        return None
    source = _bounded_manifest_path(root, entry.get("source_path"), "source")
    crop = _bounded_manifest_path(root, entry.get("crop_path"), "review/evidence")
    if source is None or crop is None or not source.is_file() or not crop.is_file():
        return None
    if _sha256(source) != str(entry.get("source_sha256", "")):
        return None
    if _sha256(crop) != str(entry.get("crop_sha256", "")):
        return None
    return crop


def _formulas_by_page(final: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for page in final.get("pages", []):
        image_index = int(page.get("source_image_index", 1))
        formulas = result.setdefault(image_index, [])
        for section in page.get("product_sections", []):
            formulas.extend(section.get("formulas", []))
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
) -> list[float] | None:
    slot_bbox: list[float] | None = None
    slot_height = 0.0
    if content_bbox and total > 0:
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
    primary = _matching_tokens(page.tokens, primary_values)
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
        return _union(candidate, slot_bbox) if slot_bbox else candidate

    return slot_bbox


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
