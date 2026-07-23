"""识别缓存：基于图片哈希和模型版本的分阶段缓存。"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from .knowledge.database import KnowledgeDB

logger = logging.getLogger(__name__)


def compute_image_hash(image_path: Path) -> str:
    """计算图片 SHA256。"""
    h = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def build_cache_key(
    image_hash: str,
    stage: str,
    provider: str = "",
    model: str = "",
    prompt_version: str = "",
    preprocess_version: str = "v2",
) -> str:
    """构建缓存键。"""
    parts = [image_hash[:16], stage, provider, model, prompt_version, preprocess_version]
    return ":".join(p for p in parts if p)


class RecognitionCache:
    """识别缓存管理器。"""

    def __init__(self, db: KnowledgeDB) -> None:
        self.db = db

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """查询缓存。"""
        result = self.db.get_cache(cache_key)
        if result:
            logger.debug("缓存命中: %s", cache_key)
        return result

    def set(
        self,
        cache_key: str,
        image_hash: str,
        stage: str,
        result_path: str,
        model: str = "",
        version: str = "",
    ) -> None:
        """写入缓存。"""
        self.db.set_cache(cache_key, image_hash, stage, result_path, model, version)

    def invalidate_for_image(self, image_hash: str) -> None:
        """图片变化时失效所有相关缓存。"""
        self.db.invalidate_cache(image_hash)
        logger.info("已失效图片缓存: %s...", image_hash[:12])

    def check_ocr_cache(self, image_path: Path, provider: str, model: str) -> dict[str, Any] | None:
        """检查 OCR 缓存。"""
        image_hash = compute_image_hash(image_path)
        key = build_cache_key(image_hash, "ocr", provider, model)
        return self.get(key)

    def check_vision_cache(
        self, image_path: Path, provider: str, model: str, prompt_version: str
    ) -> dict[str, Any] | None:
        """检查 VLM 缓存。"""
        image_hash = compute_image_hash(image_path)
        key = build_cache_key(image_hash, "vision", provider, model, prompt_version)
        return self.get(key)
