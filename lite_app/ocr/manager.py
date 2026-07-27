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


class OCRUnavailableError(RuntimeError):
    """The configured real OCR provider cannot be constructed or loaded."""


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
        self._last_error: str | None = None

    def configure(self, config: dict[str, Any]) -> None:
        """配置 OCR 参数（不立即加载模型）。"""
        if config != self._config:
            self._provider = None
            self._last_error = None
        self._config = config

    @property
    def is_available(self) -> bool:
        """OCR 是否可用（已配置且已加载）。"""
        return (
            self._last_error is None
            and self._provider is not None
            and self._provider.is_loaded
        )

    @property
    def is_configured(self) -> bool:
        """OCR 是否已配置启用。"""
        return self._config.get("enabled", False)

    @property
    def provider_name(self) -> str:
        if self._last_error:
            return "unavailable"
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

            provider_name = self._config.get("provider", "")

            if provider_name == "paddleocr_v6":
                try:
                    from .paddleocr_v6 import PaddleOCRv6Provider
                    self._provider = PaddleOCRv6Provider(
                        device=self._config.get("device", "cpu"),
                        tier=self._config.get("tier", "medium"),
                        minimum_score=float(self._config.get("minimum_score", 0.45)),
                        retention_score=float(
                            self._config.get("retention_score", 0.25)
                        ),
                        acceptance_score=float(
                            self._config.get(
                                "acceptance_score",
                                self._config.get("minimum_score", 0.45),
                            )
                        ),
                        use_textline_orientation=self._config.get("use_textline_orientation", True),
                    )
                except Exception as e:
                    self._last_error = str(e)
                    raise OCRUnavailableError(f"PaddleOCR 不可用: {e}") from e
            elif provider_name == "mock":
                self._provider = MockOCRProvider()
            else:
                raise OCRUnavailableError(f"OCR Provider 未配置或不支持: {provider_name!r}")

            return self._provider

    def ensure_loaded(self) -> None:
        """确保模型已加载。"""
        provider = self.get_provider()
        if not provider.is_loaded:
            try:
                provider.load()
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
                raise OCRUnavailableError(f"OCR 加载失败: {exc}") from exc

    async def recognize_async(self, image_path: Path) -> OCRPage:
        """异步调用 OCR（在线程中执行同步推理）。"""
        provider = self.get_provider()
        try:
            page = await asyncio.to_thread(provider.recognize, image_path)
            self._last_error = None
            return page
        except Exception as exc:
            self._last_error = str(exc)
            raise OCRUnavailableError(f"OCR 识别失败: {exc}") from exc

    def get_status(self) -> dict[str, Any]:
        """获取引擎状态。"""
        configured_provider = self._config.get("provider", "")
        effective_provider = (
            "unavailable"
            if self._last_error
            else (
                self._provider.provider_name
                if self._provider is not None
                else configured_provider
            )
        )
        from .paddleocr_v6 import TIER_MODELS

        tier = self._config.get("tier", "medium")
        models = TIER_MODELS.get(tier, {})
        return {
            "enabled": self._config.get("enabled", False),
            "loaded": self.is_available,
            "configured_provider": configured_provider,
            "effective_provider": effective_provider,
            "provider": effective_provider,
            "tier": tier,
            "device": self._config.get("device", "cpu"),
            "det_model": models.get("text_detection_model_name", ""),
            "rec_model": models.get("text_recognition_model_name", ""),
            "last_error": self._last_error,
        }

    @classmethod
    def reset(cls) -> None:
        """重置单例（测试用）。"""
        cls._instance = None
