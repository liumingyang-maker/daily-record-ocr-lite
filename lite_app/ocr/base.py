"""OCR Provider 抽象接口和标准数据结构。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OCRToken:
    """单个 OCR 识别文本框。"""
    id: str
    text: str
    confidence: float
    polygon: list[list[float]]
    bbox: list[float]  # [x_min, y_min, x_max, y_max] 像素坐标
    center_x: float
    center_y: float
    line_index: int | None = None
    source_variant: str = "base"
    raw: dict = field(default_factory=dict)


@dataclass
class OCRPage:
    """单张图片的 OCR 识别结果。"""
    image_index: int
    width: int
    height: int
    tokens: list[OCRToken]
    average_confidence: float
    provider: str
    model: str
    elapsed_ms: int
    warnings: list[str] = field(default_factory=list)

    def to_evidence_json(self) -> dict:
        """转为传给视觉模型的压缩证据格式（归一化坐标）。"""
        w, h = self.width, self.height
        tokens = []
        for t in self.tokens:
            tokens.append({
                "id": t.id,
                "text": t.text,
                "confidence": round(t.confidence, 3),
                "center": [
                    round(t.center_x / w, 4) if w else 0,
                    round(t.center_y / h, 4) if h else 0,
                ],
                "bbox": [
                    round(t.bbox[0] / w, 4) if w else 0,
                    round(t.bbox[1] / h, 4) if h else 0,
                    round(t.bbox[2] / w, 4) if w else 0,
                    round(t.bbox[3] / h, 4) if h else 0,
                ],
            })
        return {
            "image_index": self.image_index,
            "image_size": [w, h],
            "ocr_tokens": tokens,
        }


def scope_token_ids(page: OCRPage, image_index: int) -> OCRPage:
    """Make every token ID globally unique within a multi-page job."""
    page.image_index = image_index
    for index, token in enumerate(page.tokens, 1):
        token.id = f"p{image_index}_t{index:03d}"
    return page


class OCRProvider(ABC):
    """OCR Provider 抽象接口。"""

    @abstractmethod
    def recognize(self, image_path: Path) -> OCRPage:
        """识别单张图片，返回 OCRPage。"""
        ...

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """模型是否已加载。"""
        ...

    @abstractmethod
    def load(self) -> None:
        """加载模型。"""
        ...

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__
