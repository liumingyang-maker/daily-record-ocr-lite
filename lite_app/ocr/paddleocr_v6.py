"""PaddleOCR v6 Provider：基于 PaddleOCR 3.x 的 PP-OCRv6 实现。"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from .base import OCRPage, OCRProvider, OCRToken

logger = logging.getLogger(__name__)


class PaddleOCRv6Provider(OCRProvider):
    """PP-OCRv6 真实 OCR Provider。模型只初始化一次并复用。"""

    def __init__(
        self,
        device: str = "cpu",
        tier: str = "medium",
        minimum_score: float = 0.45,
        use_textline_orientation: bool = True,
    ) -> None:
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
                self._model = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=self._use_textline_orientation,
                    device=self._device,
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
            model=f"pp-ocrv6-{self._tier}",
            elapsed_ms=elapsed,
            warnings=warnings,
        )

    def _parse_result(self, result: Any, img_width: int, img_height: int) -> list[OCRToken]:
        """解析 PaddleOCR 3.x predict() 返回结构。"""
        tokens: list[OCRToken] = []

        try:
            # PaddleOCR 3.x 返回格式适配
            if isinstance(result, list) and len(result) > 0:
                page_result = result[0]
            else:
                page_result = result

            # 尝试获取 rec_texts, rec_scores, rec_polys
            rec_texts = None
            rec_scores = None
            rec_polys = None

            if hasattr(page_result, "rec_texts"):
                rec_texts = page_result.rec_texts
                rec_scores = page_result.rec_scores
                rec_polys = page_result.rec_polys
            elif isinstance(page_result, dict):
                rec_texts = page_result.get("rec_texts", [])
                rec_scores = page_result.get("rec_scores", [])
                rec_polys = page_result.get("rec_polys", [])
            elif hasattr(page_result, "__getitem__"):
                # 可能是嵌套结构
                if "rec_texts" in page_result:
                    rec_texts = page_result["rec_texts"]
                    rec_scores = page_result["rec_scores"]
                    rec_polys = page_result["rec_polys"]

            if rec_texts is None:
                logger.warning("无法解析 PaddleOCR 返回结构: %s", type(page_result))
                return tokens

            for i, (text, score) in enumerate(zip(rec_texts, rec_scores)):
                polygon = []
                bbox = [0.0, 0.0, 0.0, 0.0]

                if rec_polys is not None and i < len(rec_polys):
                    poly = rec_polys[i]
                    # poly 可能是 numpy array 或 list
                    if hasattr(poly, "tolist"):
                        poly = poly.tolist()
                    polygon = [[float(p[0]), float(p[1])] for p in poly]
                    xs = [p[0] for p in polygon]
                    ys = [p[1] for p in polygon]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
                
                center_x = (bbox[0] + bbox[2]) / 2 if bbox[2] > 0 else 0
                center_y = (bbox[1] + bbox[3]) / 2 if bbox[3] > 0 else 0

                tokens.append(OCRToken(
                    id=f"p1_t{i+1:03d}",
                    text=str(text),
                    confidence=float(score),
                    polygon=polygon,
                    bbox=bbox,
                    center_x=center_x,
                    center_y=center_y,
                    line_index=None,
                    source_variant="base",
                    raw={"text": text, "score": float(score)},
                ))

        except Exception as e:
            logger.error("解析 PaddleOCR 结果出错: %s", e)

        return tokens
