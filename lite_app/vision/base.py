"""视觉模型 Provider 抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class VisionProviderError(Exception):
    """Provider 调用错误。"""
    pass


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
