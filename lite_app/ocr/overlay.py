"""OCR Overlay 工具：在图片上绘制文字框、token id 和置信度。"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .base import OCRPage

logger = logging.getLogger(__name__)


def generate_overlay(
    image_path: Path,
    ocr_page: OCRPage,
    output_path: Path,
    show_text: bool = True,
    show_confidence: bool = True,
    show_token_id: bool = False,
) -> Path:
    """
    在图片上绘制 OCR 检测结果 overlay。

    绘制内容：
    - 文字框（多边形）
    - token id（可选）
    - 置信度（可选）
    - 文本内容（可选）
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 尝试加载字体
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        font_small = ImageFont.truetype("arial.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
        font_small = font

    for token in ocr_page.tokens:
        # 根据置信度选择颜色
        if token.confidence >= 0.9:
            color = (0, 180, 0)  # 绿色：高置信度
        elif token.confidence >= 0.7:
            color = (200, 150, 0)  # 黄色：中置信度
        else:
            color = (220, 0, 0)  # 红色：低置信度

        # 绘制多边形框
        if token.polygon and len(token.polygon) >= 3:
            polygon_points = [(p[0], p[1]) for p in token.polygon]
            draw.polygon(polygon_points, outline=color, width=2)
        elif token.bbox and len(token.bbox) == 4:
            x0, y0, x1, y1 = token.bbox
            draw.rectangle([x0, y0, x1, y1], outline=color, width=2)

        # 标注位置
        label_x = token.bbox[0] if token.bbox else 0
        label_y = max(0, (token.bbox[1] - 16) if token.bbox else 0)

        labels = []
        if show_token_id:
            labels.append(token.id)
        if show_text:
            labels.append(token.text)
        if show_confidence:
            labels.append(f"{token.confidence:.2f}")

        label_text = " | ".join(labels)
        if label_text:
            # 绘制背景
            bbox = draw.textbbox((label_x, label_y), label_text, font=font_small)
            draw.rectangle(
                [bbox[0] - 1, bbox[1] - 1, bbox[2] + 1, bbox[3] + 1],
                fill=(255, 255, 255, 200),
            )
            draw.text((label_x, label_y), label_text, fill=color, font=font_small)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="JPEG", quality=90)
    logger.info("Overlay 已生成: %s (%d tokens)", output_path.name, len(ocr_page.tokens))
    return output_path
