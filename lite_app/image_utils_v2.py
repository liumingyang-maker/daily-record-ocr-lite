"""增强版图片预处理：VLM/OCR 双图输出，OpenCV 可选增强。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

ROTATION_MAP: dict[str, int] = {
    "0": 0,
    "90cw": -90,
    "90ccw": 90,
    "180": 180,
}


class ImageProcessError(Exception):
    """图片处理错误。"""
    pass


def prepare_dual_images(
    source_path: Path,
    vlm_output: Path,
    ocr_output: Path,
    rotation: str = "auto",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    生成 VLM 图和 OCR 图两个版本。

    VLM 图：保留布局上下文，轻度处理。
    OCR 图：灰度、CLAHE、锐化等增强。
    """
    if config is None:
        config = {}

    max_side_vlm = config.get("max_side_vlm", 2400)
    max_side_ocr = config.get("max_side_ocr", 2600)
    jpeg_quality = config.get("jpeg_quality", 94)
    auto_rotate = config.get("auto_rotate", True)

    try:
        img = Image.open(source_path)
    except UnidentifiedImageError:
        raise ImageProcessError(f"文件不是可识别的图片: {source_path.name}")
    except Exception as e:
        raise ImageProcessError(f"无法打开图片 {source_path.name}: {e}")

    # EXIF 方向
    img = ImageOps.exif_transpose(img)

    # 转 RGB
    img = _to_rgb(img)

    # 旋转
    img = _apply_rotation(img, rotation, auto_rotate)

    # VLM 图：保留色彩和布局，只做缩放
    vlm_img = _resize_max_side(img, max_side_vlm)
    vlm_output.parent.mkdir(parents=True, exist_ok=True)
    vlm_img.save(vlm_output, format="JPEG", quality=jpeg_quality, optimize=True)

    # OCR 图：灰度 + 增强
    ocr_img = _resize_max_side(img, max_side_ocr)
    ocr_img = _enhance_for_ocr(ocr_img, config)
    ocr_output.parent.mkdir(parents=True, exist_ok=True)
    ocr_img.save(ocr_output, format="JPEG", quality=jpeg_quality, optimize=True)

    vlm_size = vlm_img.size
    ocr_size = ocr_img.size

    logger.info(
        "双图处理完成: %s -> VLM(%dx%d) + OCR(%dx%d)",
        source_path.name, vlm_size[0], vlm_size[1], ocr_size[0], ocr_size[1],
    )

    return {
        "vlm_width": vlm_size[0],
        "vlm_height": vlm_size[1],
        "ocr_width": ocr_size[0],
        "ocr_height": ocr_size[1],
    }


def prepare_single_image(
    source_path: Path,
    output_path: Path,
    rotation: str = "auto",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """兼容旧接口：生成单张处理图。"""
    if config is None:
        config = {}

    max_side = config.get("max_side", config.get("max_side_vlm", 2400))
    jpeg_quality = config.get("jpeg_quality", 94)
    auto_rotate = config.get("auto_rotate", True)

    try:
        img = Image.open(source_path)
    except UnidentifiedImageError:
        raise ImageProcessError(f"文件不是可识别的图片: {source_path.name}")
    except Exception as e:
        raise ImageProcessError(f"无法打开图片 {source_path.name}: {e}")

    img = ImageOps.exif_transpose(img)
    img = _to_rgb(img)
    img = _apply_rotation(img, rotation, auto_rotate)
    img = _resize_max_side(img, max_side)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="JPEG", quality=jpeg_quality, optimize=True)

    width, height = img.size
    return {"width": width, "height": height}


def generate_enhanced_variant(
    ocr_image_path: Path,
    enhanced_output: Path,
    config: dict[str, Any] | None = None,
) -> bool:
    """
    生成增强版 OCR 图（CLAHE + 去阴影 + 锐化）。

    需要 OpenCV。不可用时返回 False。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.info("OpenCV 不可用，跳过增强图生成")
        return False

    img = cv2.imread(str(ocr_image_path))
    if img is None:
        return False

    # 灰度
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 轻度锐化
    kernel = np.array([[-0.5, -0.5, -0.5],
                       [-0.5,  5.0, -0.5],
                       [-0.5, -0.5, -0.5]]) / 1.0
    # 使用温和锐化
    kernel_mild = np.array([[0, -0.5, 0],
                            [-0.5, 3, -0.5],
                            [0, -0.5, 0]]) / 1.0
    sharpened = cv2.filter2D(enhanced, -1, kernel_mild)

    enhanced_output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(enhanced_output), sharpened, [cv2.IMWRITE_JPEG_QUALITY, 94])
    return True


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return img.convert("RGB")


def _apply_rotation(img: Image.Image, rotation: str, auto_rotate: bool) -> Image.Image:
    if rotation == "auto":
        if auto_rotate:
            width, height = img.size
            if height > width * 1.2:
                img = img.rotate(90, expand=True)
        return img
    angle = ROTATION_MAP.get(rotation, 0)
    if angle != 0:
        img = img.rotate(angle, expand=True)
    return img


def _resize_max_side(img: Image.Image, max_side: int) -> Image.Image:
    width, height = img.size
    longest = max(width, height)
    if longest <= max_side:
        return img
    ratio = max_side / longest
    new_width = int(width * ratio)
    new_height = int(height * ratio)
    return img.resize((new_width, new_height), Image.LANCZOS)


def _enhance_for_ocr(img: Image.Image, config: dict[str, Any]) -> Image.Image:
    """OCR 图增强：灰度 + 对比度。不依赖 OpenCV 的基础增强。"""
    # 灰度化
    gray = img.convert("L")

    # 尝试 OpenCV CLAHE
    if config.get("enable_clahe", True):
        try:
            import cv2
            import numpy as np
            arr = np.array(gray)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(arr)
            return Image.fromarray(enhanced)
        except ImportError:
            pass

    # 无 OpenCV 时用 Pillow 对比度增强
    from PIL import ImageEnhance
    enhancer = ImageEnhance.Contrast(gray)
    return enhancer.enhance(1.3)
