"""OCR 模型管理器：单例、惰性加载、线程安全。"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from .base import OCRPage, OCRProvider
from .mock import MockOCRProvider

logger = logging.getLogger(__name__)


class OCRModelManager:
    """OCR 模型单例管理器。"""

    _instance: OCRModelManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> OCRModelManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._provider: OCRProvider | None = None
        self._provider_lock = threading.Lock()
        self._config: dict[str, Any] = {}

    def configure(self, config: dict[str, Any]) -> None:
        """配置 OCR 参数（不立即加载模型）。"""
        self._config = config

    @property
    def is_available(self) -> bool:
        """OCR 是否可用（已配置且已加载）。"""
        return self._provider is not None and self._provider.is_loaded

    @property
    def is_configured(self) -> bool:
        """OCR 是否已配置启用。"""
        return self._config.get("enabled", False)

    @property
    def provider_name(self) -> str:
        if self._provider:
            return self._provider.provider_name
        return self._config.get("provider", "none")

    def get_provider(self) -> OCRProvider:
        """获取或创建 OCR Provider（惰性加载）。"""
        if self._provider is not None:
            return self._provider

        with self._provider_lock:
            if self._provider is not None:
                return self._provider

            provider_name = self._config.get("provider", "mock")

            if provider_name == "paddleocr_v6":
                try:
                    from .paddleocr_v6 import PaddleOCRv6Provider
                    self._provider = PaddleOCRv6Provider(
                        device=self._config.get("device", "cpu"),
                        tier=self._config.get("tier", "medium"),
                        minimum_score=float(self._config.get("minimum_score", 0.45)),
                        use_textline_orientation=self._config.get("use_textline_orientation", True),
                    )
                except Exception as e:
                    logger.warning("PaddleOCR 不可用，降级为 Mock: %s", e)
                    self._provider = MockOCRProvider()
            else:
                self._provider = MockOCRProvider()

            return self._provider

    def ensure_loaded(self) -> None:
        """确保模型已加载。"""
        provider = self.get_provider()
        if not provider.is_loaded:
            provider.load()

    async def recognize_async(self, image_path: Path) -> OCRPage:
        """异步调用 OCR（在线程中执行同步推理）。"""
        provider = self.get_provider()
        return await asyncio.to_thread(provider.recognize, image_path)

    def get_status(self) -> dict[str, Any]:
        """获取引擎状态。"""
        return {
            "enabled": self._config.get("enabled", False),
            "loaded": self.is_available,
            "provider": self._config.get("provider", "mock"),
            "tier": self._config.get("tier", "medium"),
            "device": self._config.get("device", "cpu"),
        }

    @classmethod
    def reset(cls) -> None:
        """重置单例（测试用）。"""
        cls._instance = None
