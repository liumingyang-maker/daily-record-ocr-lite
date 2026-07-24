"""PaddleOCR v6 Provider：基于 PaddleOCR 3.x 的 PP-OCRv6 实现。"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from .base import OCRPage, OCRProvider, OCRToken

logger = logging.getLogger(__name__)

TIER_MODELS = {
    tier: {
        "text_detection_model_name": f"PP-OCRv6_{tier}_det",
        "text_recognition_model_name": f"PP-OCRv6_{tier}_rec",
    }
    for tier in ("tiny", "small", "medium")
}


class OCRResultParseError(RuntimeError):
    """PaddleOCR returned a shape the installed adapter cannot interpret."""


class PaddleOCRv6Provider(OCRProvider):
    """PP-OCRv6 真实 OCR Provider。模型只初始化一次并复用。"""

    def __init__(
        self,
        device: str = "cpu",
        tier: str = "medium",
        minimum_score: float = 0.45,
        use_textline_orientation: bool = True,
    ) -> None:
        if tier not in TIER_MODELS:
            raise ValueError(f"不支持的 PP-OCRv6 tier: {tier}")
        self._device = device
        self._tier = tier
        self._minimum_score = minimum_score
        self._use_textline_orientation = use_textline_orientation
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """惰性加载 PaddleOCR 模型（线程安全）。"""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            logger.info("正在加载 PP-OCRv6 模型 (tier=%s, device=%s)...", self._tier, self._device)
            start = time.time()
            try:
                from paddleocr import PaddleOCR
            except ImportError as e:
                raise RuntimeError(
                    "PaddleOCR 未安装。请运行: pip install -r requirements-ocr.txt"
                ) from e

            try:
                engine_options = {}
                if self._device.lower().split(":", 1)[0] == "cpu":
                    # Paddle 3.3.x can crash in the oneDNN/PIR executor during
                    # PP-OCR inference. Prefer correctness over CPU acceleration.
                    engine_options["enable_mkldnn"] = False
                self._model = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=self._use_textline_orientation,
                    device=self._device,
                    **engine_options,
                    **TIER_MODELS[self._tier],
                )
            except Exception as e:
                raise RuntimeError(
                    f"PaddleOCR 模型初始化失败: {e}。"
                    f"请确认 paddlepaddle 和 paddleocr 版本兼容。"
                ) from e

            elapsed = time.time() - start
            logger.info("PP-OCRv6 模型加载完成，耗时 %.1f 秒", elapsed)

    def recognize(self, image_path: Path) -> OCRPage:
        """识别单张图片。"""
        if not self.is_loaded:
            self.load()

        from PIL import Image
        img = Image.open(image_path)
        width, height = img.size

        start = time.time()
        try:
            result = self._model.predict(str(image_path))
        except Exception as e:
            raise RuntimeError(f"PaddleOCR 推理失败: {e}") from e

        elapsed = int((time.time() - start) * 1000)
        tokens = self._parse_result(result, width, height)

        # 过滤低置信度
        tokens = [t for t in tokens if t.confidence >= self._minimum_score]
        avg_conf = sum(t.confidence for t in tokens) / len(tokens) if tokens else 0.0

        warnings: list[str] = []
        if not tokens:
            warnings.append("OCR 未检测到任何文本框")

        return OCRPage(
            image_index=1,
            width=width,
            height=height,
            tokens=tokens,
            average_confidence=round(avg_conf, 4),
            provider="paddleocr_v6",
            model=f"PP-OCRv6_{self._tier}",
            elapsed_ms=elapsed,
            warnings=warnings,
        )

    def _parse_result(self, result: Any, img_width: int, img_height: int) -> list[OCRToken]:
        """解析 PaddleOCR 3.x predict() 返回结构。"""
        if isinstance(result, (list, tuple)):
            if not result:
                return []
            page_result = result[0]
        else:
            page_result = result

        data: Any = page_result
        if not isinstance(data, dict) and hasattr(page_result, "json"):
            data = page_result.json
            if callable(data):
                data = data()
        if isinstance(data, dict) and isinstance(data.get("res"), dict):
            data = data["res"]

        if isinstance(data, dict):
            rec_texts = data.get("rec_texts")
            rec_scores = data.get("rec_scores")
            rec_polys = data.get("rec_polys", data.get("dt_polys"))
        else:
            rec_texts = getattr(page_result, "rec_texts", None)
            rec_scores = getattr(page_result, "rec_scores", None)
            rec_polys = getattr(
                page_result,
                "rec_polys",
                getattr(page_result, "dt_polys", None),
            )

        if rec_texts is None or rec_scores is None:
            raise OCRResultParseError(
                f"无法解析 PaddleOCR 返回结构: {type(page_result).__name__}"
            )
        if len(rec_texts) != len(rec_scores):
            raise OCRResultParseError(
                f"PaddleOCR 文本与置信度数量不一致: {len(rec_texts)} != {len(rec_scores)}"
            )
        if rec_texts and rec_polys is None:
            raise OCRResultParseError("PaddleOCR 返回文本但缺少 rec_polys/dt_polys")

        tokens: list[OCRToken] = []
        for index, (text, score) in enumerate(zip(rec_texts, rec_scores), 1):
            poly = rec_polys[index - 1]
            if hasattr(poly, "tolist"):
                poly = poly.tolist()
            try:
                polygon = [[float(point[0]), float(point[1])] for point in poly]
            except (TypeError, ValueError, IndexError) as exc:
                raise OCRResultParseError(
                    f"PaddleOCR 第 {index} 个 polygon 非法"
                ) from exc
            if not polygon:
                raise OCRResultParseError(f"PaddleOCR 第 {index} 个 polygon 为空")
            xs = [point[0] for point in polygon]
            ys = [point[1] for point in polygon]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
            tokens.append(
                OCRToken(
                    id=f"t{index:03d}",
                    text=str(text),
                    confidence=float(score),
                    polygon=polygon,
                    bbox=bbox,
                    center_x=(bbox[0] + bbox[2]) / 2,
                    center_y=(bbox[1] + bbox[3]) / 2,
                    line_index=None,
                    source_variant="base",
                    raw={"text": str(text), "score": float(score)},
                )
            )
        return tokens
