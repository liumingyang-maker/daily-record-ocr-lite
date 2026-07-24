"""Local OCR/VLM recheck with one-shot limits and FinalResult synchronization."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from PIL import Image

from ..config import load_fusion_rules
from ..contracts import load_schema_file
from ..final_result import FinalResultService
from ..fusion.engine import Candidate, FusionEngine
from ..knowledge.matcher import normalize_text
from ..storage import read_json_optional, write_json_atomic


class RecheckError(RuntimeError):
    """A local recheck request is invalid or cannot complete safely."""


def crop_field_region(
    image_path: Path,
    bbox: list[float],
    output_dir: Path,
    field_id: str,
    context_ratio: float = 1.0,
) -> dict[str, Path]:
    """Create tight and context crops from normalized or pixel coordinates."""
    if len(bbox) != 4 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise RecheckError(f"字段 {field_id} 的 bbox 无效")

    with Image.open(image_path) as source:
        image = source.convert("RGB")
    image_width, image_height = image.size
    coordinates = [float(value) for value in bbox]
    if all(0 <= value <= 1 for value in coordinates):
        coordinates = [
            coordinates[0] * image_width,
            coordinates[1] * image_height,
            coordinates[2] * image_width,
            coordinates[3] * image_height,
        ]

    x_min, y_min, x_max, y_max = coordinates
    field_width = x_max - x_min
    field_height = y_max - y_min
    tight_box = (
        max(0, int(round(x_min))),
        max(0, int(round(y_min))),
        min(image_width, int(round(x_max))),
        min(image_height, int(round(y_max))),
    )
    context_box = (
        max(0, int(round(x_min - field_width * context_ratio))),
        max(0, int(round(y_min - field_height * context_ratio * 1.5))),
        min(image_width, int(round(x_max + field_width * context_ratio))),
        min(image_height, int(round(y_max + field_height * context_ratio * 1.5))),
    )
    if tight_box[2] <= tight_box[0] or tight_box[3] <= tight_box[1]:
        raise RecheckError(f"字段 {field_id} 的 bbox 裁切结果为空")

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = hashlib.sha256(field_id.encode("utf-8")).hexdigest()[:16]
    tight_path = output_dir / f"{safe_id}_tight.jpg"
    context_path = output_dir / f"{safe_id}_context.jpg"
    image.crop(tight_box).save(tight_path, "JPEG", quality=95)
    image.crop(context_box).save(context_path, "JPEG", quality=95)
    return {"tight": tight_path, "context": context_path}


async def recheck_fields(
    job_id: str,
    job_dir: Path,
    job: dict[str, Any],
    field_ids: list[str],
    ocr_manager: Any,
    vision_provider: Any,
) -> dict[str, Any]:
    """Recheck selected fields, call VLM once, re-fuse, and update FinalResult."""
    requested = list(dict.fromkeys(str(item) for item in field_ids if str(item)))
    if not requested:
        raise RecheckError("field_ids 不能为空")

    final_service = FinalResultService(job_dir)
    final = final_service.load()
    located = _locate_fields(final)
    missing = [field_id for field_id in requested if field_id not in located]
    if missing:
        raise RecheckError(f"字段不存在: {', '.join(missing)}")

    selected = []
    crop_paths: list[Path] = []
    for field_id in requested:
        field = located[field_id]
        if int(field.get("recheck_count", 0)) >= 1:
            raise RecheckError(f"字段 {field_id} 自动局部复核最多一次")
        bbox = field.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise RecheckError(f"字段 {field_id} 缺少有效 bbox")
        image_path = _source_image(job_dir, job, int(field["source_image_index"]))
        crops = crop_field_region(
            image_path,
            bbox,
            job_dir / "review" / "crops",
            field_id,
        )
        ocr_page = await ocr_manager.recognize_async(crops["tight"])
        ocr_value = " ".join(
            token.text.strip() for token in ocr_page.tokens if token.text.strip()
        )
        ocr_confidence = float(ocr_page.average_confidence)
        selected.append(
            {
                "field_id": field_id,
                "field": field,
                "ocr_value": ocr_value,
                "ocr_confidence": ocr_confidence,
                "tight_crop": str(crops["tight"].relative_to(job_dir)),
                "context_crop": str(crops["context"].relative_to(job_dir)),
            }
        )
        crop_paths.extend([crops["tight"], crops["context"]])

    prompt = _build_recheck_prompt(selected)
    if vision_provider is None:
        response = {
            "schema_version": "recheck-v1",
            "fields": [
                {
                    "field_id": item["field_id"],
                    "value": item["ocr_value"],
                    "confidence": item["ocr_confidence"],
                }
                for item in selected
            ],
        }
    else:
        raw = await vision_provider.analyze(
            crop_paths,
            "你是局部手写字段复核器。严格返回 recheck-v1 JSON。",
            prompt,
            load_schema_file("recheck-v1.schema.json"),
        )
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RecheckError(f"局部 VLM 返回非法 JSON: {exc}") from exc

    errors = sorted(
        Draft202012Validator(
            load_schema_file("recheck-v1.schema.json")
        ).iter_errors(response),
        key=lambda error: list(error.path),
    )
    if errors:
        raise RecheckError(f"局部 VLM 结果不符合 recheck-v1: {errors[0].message}")

    vlm_by_id = {
        item["field_id"]: item for item in response["fields"]
    }
    missing_vlm = [item["field_id"] for item in selected if item["field_id"] not in vlm_by_id]
    if missing_vlm:
        raise RecheckError(f"局部 VLM 缺少字段: {', '.join(missing_vlm)}")

    fusion_data = read_json_optional(job_dir / "fusion" / "result.json")
    if not isinstance(fusion_data, dict):
        fusion_data = {"fields": []}
    fusion_by_id = {
        item.get("field_id"): item for item in fusion_data.get("fields", [])
    }
    engine = FusionEngine(load_fusion_rules())
    outcomes = []
    for item in selected:
        field_id = item["field_id"]
        field = item["field"]
        local_vlm = vlm_by_id[field_id]
        field_type = _field_type(field_id, fusion_by_id.get(field_id))
        candidates = [
            Candidate(
                value=item["ocr_value"],
                normalized_value=_normalize(item["ocr_value"], field_type),
                source="local_ocr_recheck",
                confidence=item["ocr_confidence"],
                evidence=[item["tight_crop"]],
            ),
            Candidate(
                value=str(local_vlm["value"]),
                normalized_value=_normalize(str(local_vlm["value"]), field_type),
                source="local_vlm_recheck",
                confidence=float(local_vlm["confidence"]),
                evidence=[item["tight_crop"]],
            ),
        ]
        for candidate in field.get("candidates", []):
            value = str(candidate.get("value", ""))
            if value:
                candidates.append(
                    Candidate(
                        value=value,
                        normalized_value=_normalize(value, field_type),
                        source=str(candidate.get("source", "previous")),
                        confidence=float(candidate.get("confidence", 0.0)),
                        evidence=list(candidate.get("evidence", [])),
                    )
                )

        fused = engine.fuse_field(field_id, field_type, candidates)
        field.update(
            {
                "value": fused.final_value,
                "confidence": fused.final_confidence,
                "source": fused.final_source,
                "status": fused.status,
                "review_status": fused.status,
                "recheck_count": 1,
                "candidates": [
                    {
                        "value": candidate.value,
                        "source": candidate.source,
                        "confidence": candidate.confidence,
                        "evidence": candidate.evidence,
                    }
                    for candidate in candidates
                ],
                "recheck": {
                    "tight_crop": item["tight_crop"],
                    "context_crop": item["context_crop"],
                    "reasons": fused.reasons,
                },
            }
        )
        _sync_fusion_field(fusion_data, field_id, field, field_type)
        outcomes.append(
            {
                "field_id": field_id,
                "value": field["value"],
                "confidence": field["confidence"],
                "status": field["status"],
            }
        )

    final_service.replace(final)
    write_json_atomic(job_dir / "fusion" / "result.json", fusion_data)
    artifact = {
        "schema_version": "recheck-v1",
        "job_id": job_id,
        "created_at": datetime.now(UTC).isoformat(),
        "fields": outcomes,
    }
    write_json_atomic(job_dir / "review" / "recheck_result.json", artifact)
    unresolved = [
        item for item in outcomes if item["status"] in {"CONFLICT", "NEED_REVIEW", "EMPTY"}
    ]
    return {
        "status": "REVIEW_REQUIRED" if unresolved else "RESOLVED",
        "fields": outcomes,
    }


def _source_image(job_dir: Path, job: dict[str, Any], image_index: int) -> Path:
    images = job.get("images", [])
    if image_index < 1 or image_index > len(images):
        raise RecheckError(f"source_image_index 越界: {image_index}")
    image = images[image_index - 1]
    relative = image.get("prepared_ocr") or image.get("prepared") or image.get("source")
    if not relative:
        raise RecheckError(f"第 {image_index} 页没有可复核图片")
    path = (job_dir / str(relative)).resolve()
    try:
        path.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise RecheckError("复核图片路径越界") from exc
    if not path.exists():
        raise RecheckError(f"复核图片不存在: {relative}")
    return path


def _locate_fields(final: dict[str, Any]) -> dict[str, dict[str, Any]]:
    located = {}
    for page in final.get("pages", []):
        image_index = int(page.get("source_image_index", 1))
        for section in page.get("product_sections", []):
            fields = [section.get("product_or_series")]
            for formula in section.get("formulas", []):
                fields.extend([formula.get("record_date"), formula.get("notes")])
                for material in formula.get("materials", []):
                    fields.extend(
                        [material.get("name"), material.get("amount"), material.get("unit")]
                    )
                for parameter in formula.get("process_parameters", []):
                    fields.extend(
                        [parameter.get("name"), parameter.get("value"), parameter.get("unit")]
                    )
            for field in fields:
                if isinstance(field, dict) and field.get("field_id"):
                    field.setdefault("source_image_index", image_index)
                    located[str(field["field_id"])] = field
    return located


def _field_type(field_id: str, fusion: dict[str, Any] | None) -> str:
    if fusion and fusion.get("field_type"):
        return str(fusion["field_type"])
    if field_id.endswith("__amount") or field_id.endswith("__value"):
        return "amount"
    if field_id.endswith("__record_date"):
        return "date"
    return "text"


def _normalize(value: str, field_type: str) -> str:
    return value.strip() if field_type == "amount" else normalize_text(value)


def _sync_fusion_field(
    fusion: dict[str, Any],
    field_id: str,
    field: dict[str, Any],
    field_type: str,
) -> None:
    target = next(
        (item for item in fusion.get("fields", []) if item.get("field_id") == field_id),
        None,
    )
    if target is None:
        target = {"field_id": field_id, "field_type": field_type}
        fusion.setdefault("fields", []).append(target)
    target.update(
        {
            "final_value": field["value"],
            "final_confidence": field["confidence"],
            "final_source": field["source"],
            "status": field["status"],
            "candidates": field["candidates"],
            "bbox": field.get("bbox"),
            "source_image_index": field.get("source_image_index"),
            "recheck_count": 1,
        }
    )


def _build_recheck_prompt(selected: list[dict[str, Any]]) -> str:
    lines = [
        "每个字段依次提供 tight、context 两张裁图。"
        "tight 是目标字段，context 仅辅助定位。不要猜测；只返回 recheck-v1 JSON。",
    ]
    for index, item in enumerate(selected, 1):
        lines.append(
            f"{index}. images={index * 2 - 1},{index * 2}; "
            f"field_id={item['field_id']}; local_ocr={item['ocr_value']!r}"
        )
    return "\n".join(lines)
