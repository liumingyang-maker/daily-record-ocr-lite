"""图片预处理：EXIF 方向、旋转、缩放、JPEG 输出。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

# 旋转映射：用户选项 -> Pillow rotate 角度（正角度为逆时针）
ROTATION_MAP: dict[str, int] = {
    "0": 0,
    "90cw": -90,   # 顺时针 90° = Pillow -90（即 270 逆时针）
    "90ccw": 90,   # 逆时针 90° = Pillow 90
    "180": 180,
}


class ImageProcessError(Exception):
    """图片处理错误。"""
    pass


def prepare_image(
    source_path: Path,
    output_path: Path,
    rotation: str = "auto",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    处理单张图片：EXIF 方向、旋转、缩放、JPEG 输出。

    返回处理后的宽高信息。
    """
    if config is None:
        config = {}

    max_side = config.get("max_side", 2048)
    jpeg_quality = config.get("jpeg_quality", 90)
    auto_rotate = config.get("auto_rotate_portrait_to_landscape", True)
    auto_direction = config.get("auto_landscape_direction", "ccw90")

    try:
        img = Image.open(source_path)
    except UnidentifiedImageError:
        raise ImageProcessError(f"文件不是可识别的图片: {source_path.name}")
    except Exception as e:
        raise ImageProcessError(f"无法打开图片 {source_path.name}: {e}")

    # 1. 应用 EXIF 方向
    img = ImageOps.exif_transpose(img)

    # 2. 转为 RGB（处理透明通道）
    img = _to_rgb(img)

    # 3. 旋转处理
    img = _apply_rotation(img, rotation, auto_rotate, auto_direction)

    # 4. 缩放（只缩小不放大）
    img = _resize_max_side(img, max_side)

    # 5. 保存为 JPEG
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(
        output_path,
        format="JPEG",
        quality=jpeg_quality,
        optimize=True,
    )

    width, height = img.size
    logger.info(
        "图片处理完成: %s -> %s (%dx%d)",
        source_path.name,
        output_path.name,
        width,
        height,
    )
    return {"width": width, "height": height}


def _to_rgb(img: Image.Image) -> Image.Image:
    """将图片转为 RGB 模式，透明区域合成白色背景。"""
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        return background
    return img.convert("RGB")


def _apply_rotation(
    img: Image.Image,
    rotation: str,
    auto_rotate: bool,
    auto_direction: str,
) -> Image.Image:
    """应用旋转。"""
    if rotation == "auto":
        if auto_rotate:
            width, height = img.size
            # 明显竖图（高 > 宽 * 1.2）时自动旋转为横向
            if height > width * 1.2:
                angle = ROTATION_MAP.get(auto_direction, 90)
                img = img.rotate(angle, expand=True)
        return img

    angle = ROTATION_MAP.get(rotation, 0)
    if angle != 0:
        img = img.rotate(angle, expand=True)
    return img


def _resize_max_side(img: Image.Image, max_side: int) -> Image.Image:
    """最长边超过 max_side 时等比例缩小，不放大。"""
    width, height = img.size
    longest = max(width, height)
    if longest <= max_side:
        return img
    ratio = max_side / longest
    new_width = int(width * ratio)
    new_height = int(height * ratio)
    return img.resize((new_width, new_height), Image.LANCZOS)


def image_to_data_url(image_path: Path) -> str:
    """将图片文件转为 base64 data URL。"""
    import base64

    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
