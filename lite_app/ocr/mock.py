"""Mock OCR Provider：用于无 PaddleOCR 环境的测试和开发。"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from .base import OCRPage, OCRProvider, OCRToken


class MockOCRProvider(OCRProvider):
    """返回预设 OCR 结果的 Mock Provider。"""

    def __init__(self, mock_data: list[dict] | None = None) -> None:
        self._loaded = False
        self._mock_data = mock_data

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        self._loaded = True

    def recognize(self, image_path: Path) -> OCRPage:
        if not self._loaded:
            self.load()

        start = time.time()
        img = Image.open(image_path)
        width, height = img.size

        tokens: list[OCRToken] = []
        if self._mock_data:
            for i, item in enumerate(self._mock_data):
                bbox = item.get("bbox", [0.1, 0.1, 0.3, 0.15])
                # 归一化坐标转像素
                px_bbox = [
                    bbox[0] * width,
                    bbox[1] * height,
                    bbox[2] * width,
                    bbox[3] * height,
                ]
                tokens.append(OCRToken(
                    id=f"p1_t{i+1:03d}",
                    text=item.get("text", ""),
                    confidence=item.get("confidence", 0.90),
                    polygon=[
                        [px_bbox[0], px_bbox[1]],
                        [px_bbox[2], px_bbox[1]],
                        [px_bbox[2], px_bbox[3]],
                        [px_bbox[0], px_bbox[3]],
                    ],
                    bbox=px_bbox,
                    center_x=(px_bbox[0] + px_bbox[2]) / 2,
                    center_y=(px_bbox[1] + px_bbox[3]) / 2,
                    line_index=item.get("line_index"),
                    source_variant="base",
                    raw=item,
                ))
        else:
            # 默认生成一些模拟 token
            default_tokens = [
                {"text": "PA66", "confidence": 0.96, "bbox": [0.10, 0.20, 0.20, 0.25]},
                {"text": "GF30", "confidence": 0.94, "bbox": [0.25, 0.20, 0.35, 0.25]},
                {"text": "60", "confidence": 0.93, "bbox": [0.10, 0.28, 0.16, 0.33]},
                {"text": "30", "confidence": 0.92, "bbox": [0.25, 0.28, 0.31, 0.33]},
                {"text": "工艺", "confidence": 0.91, "bbox": [0.10, 0.50, 0.18, 0.55]},
                {"text": "50Hz", "confidence": 0.89, "bbox": [0.20, 0.50, 0.30, 0.55]},
            ]
            for i, item in enumerate(default_tokens):
                bbox = item["bbox"]
                px_bbox = [
                    bbox[0] * width,
                    bbox[1] * height,
                    bbox[2] * width,
                    bbox[3] * height,
                ]
                tokens.append(OCRToken(
                    id=f"p1_t{i+1:03d}",
                    text=item["text"],
                    confidence=item["confidence"],
                    polygon=[
                        [px_bbox[0], px_bbox[1]],
                        [px_bbox[2], px_bbox[1]],
                        [px_bbox[2], px_bbox[3]],
                        [px_bbox[0], px_bbox[3]],
                    ],
                    bbox=px_bbox,
                    center_x=(px_bbox[0] + px_bbox[2]) / 2,
                    center_y=(px_bbox[1] + px_bbox[3]) / 2,
                    line_index=i // 2,
                    source_variant="base",
                    raw=item,
                ))

        elapsed = int((time.time() - start) * 1000)
        avg_conf = sum(t.confidence for t in tokens) / len(tokens) if tokens else 0.0

        return OCRPage(
            image_index=1,
            width=width,
            height=height,
            tokens=tokens,
            average_confidence=round(avg_conf, 4),
            provider="mock",
            model="mock",
            elapsed_ms=elapsed,
            warnings=[],
        )
