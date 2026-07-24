"""视觉模型 Provider 抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class VisionProviderError(RuntimeError):
    """Provider 调用错误。"""
    pass


class VisionConfigurationError(VisionProviderError):
    """Vision provider configuration is missing or invalid."""


class VisionConnectionError(VisionProviderError):
    """Vision provider could not be reached or returned an invalid response."""


class VisionProvider(ABC):
    """视觉模型 Provider 抽象接口。"""

    @abstractmethod
    async def analyze(
        self,
        image_paths: list[Path],
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> str:
        """返回模型原始文本响应。"""
        ...
