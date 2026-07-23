"""局部复核：裁图 + 局部 OCR/VLM 重新识别。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)


def crop_field_region(
    image_path: Path,
    bbox: list[float],
    output_dir: Path,
    field_id: str,
    context_ratio: float = 1.0,
) -> dict[str, Path]:
    """
    裁切字段区域，生成 context 和 tight 两个版本。

    bbox: [x_min, y_min, x_max, y_max] 像素坐标
    context_ratio: 上下文扩展比例
    """
    img = Image.open(image_path)
    img_w, img_h = img.size

    x_min, y_min, x_max, y_max = bbox
    field_w = x_max - x_min
    field_h = y_max - y_min

    # tight crop
    tight_box = (
        max(0, int(x_min)),
        max(0, int(y_min)),
        min(img_w, int(x_max)),
        min(img_h, int(y_max)),
    )

    # context crop（扩展边距）
    pad_x = field_w * context_ratio
    pad_y = field_h * context_ratio * 1.5
    context_box = (
        max(0, int(x_min - pad_x)),
        max(0, int(y_min - pad_y)),
        min(img_w, int(x_max + pad_x)),
        min(img_h, int(y_max + pad_y)),
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    tight_path = output_dir / f"{field_id}_tight.jpg"
    context_path = output_dir / f"{field_id}_context.jpg"

    img.crop(tight_box).save(tight_path, format="JPEG", quality=95)
    img.crop(context_box).save(context_path, format="JPEG", quality=95)

    return {"tight": tight_path, "context": context_path}


async def local_recheck_fields(
    fields: list[dict[str, Any]],
    image_path: Path,
    crops_dir: Path,
    ocr_manager: Any,
    vision_provider: Any,
) -> list[dict[str, Any]]:
    """
    对冲突字段执行局部复核。

    最多一次局部复核，不无限重试。
    返回更新后的字段列表。
    """
    if not fields:
        return fields

    # 裁图
    for field in fields:
        bbox = field.get("bbox")
        field_id = field.get("field_id", "unknown")
        if bbox and len(bbox) == 4:
            try:
                crops = crop_field_region(image_path, bbox, crops_dir, field_id)
                field["crop_tight"] = str(crops["tight"].name)
                field["crop_context"] = str(crops["context"].name)
            except Exception as e:
                logger.warning("裁图失败 %s: %s", field_id, e)

    # 局部 OCR
    recheck_results: list[dict[str, Any]] = []
    for field in fields:
        crop_name = field.get("crop_context")
        if not crop_name:
            continue
        crop_path = crops_dir / crop_name
        if not crop_path.exists():
            continue

        try:
            ocr_page = await ocr_manager.recognize_async(crop_path)
            local_texts = [t.text for t in ocr_page.tokens]
            field["local_ocr_texts"] = local_texts
            field["local_ocr_confidence"] = ocr_page.average_confidence
        except Exception as e:
            logger.warning("局部 OCR 失败 %s: %s", field.get("field_id"), e)

    # 局部 VLM（批量一次调用）
    crop_paths = []
    crop_field_ids = []
    for field in fields:
        crop_name = field.get("crop_context")
        if crop_name:
            crop_path = crops_dir / crop_name
            if crop_path.exists():
                crop_paths.append(crop_path)
                crop_field_ids.append(field.get("field_id", ""))

    if crop_paths and vision_provider:
        try:
            prompt = _build_recheck_prompt(fields, crop_field_ids)
            raw = await vision_provider.analyze(
                crop_paths,
                "你是手写文字复核员。只返回 JSON。",
                prompt,
                {},
            )
            import json
            try:
                recheck_data = json.loads(raw)
                conflicts = recheck_data.get("conflicts", [])
                for item in conflicts:
                    fid = item.get("field_id", "")
                    for field in fields:
                        if field.get("field_id") == fid:
                            field["local_vlm_value"] = item.get("value", "")
                            field["local_vlm_confidence"] = item.get("confidence", 0)
                            field["local_vlm_reason"] = item.get("reason", "")
            except (json.JSONDecodeError, KeyError):
                logger.warning("局部 VLM 响应解析失败")
        except Exception as e:
            logger.warning("局部 VLM 调用失败: %s", e)

    return fields


def _build_recheck_prompt(fields: list[dict[str, Any]], field_ids: list[str]) -> str:
    """构建局部复核提示词。"""
    lines = ["以下是需要复核的冲突字段，请仔细观察图片中的手写内容：", ""]
    for field in fields:
        fid = field.get("field_id", "")
        ftype = field.get("field_type", "")
        ocr_val = ""
        vlm_val = ""
        for c in field.get("candidates", []):
            if c.get("source", "").startswith("ocr"):
                ocr_val = c.get("value", "")
            elif c.get("source") == "vlm":
                vlm_val = c.get("value", "")
        lines.append(f"- field_id: {fid}, 类型: {ftype}, OCR: {ocr_val}, VLM: {vlm_val}")

    lines.append("")
    lines.append("请返回 JSON：")
    lines.append('{"conflicts": [{"field_id": "...", "value": "你看到的真实值", "confidence": 0.0-1.0, "reason": "判断依据"}]}')
    lines.append("")
    lines.append("规则：看不清时 confidence 设低，不要猜测。数字和小数点必须严格按原图。")
    return "\n".join(lines)
