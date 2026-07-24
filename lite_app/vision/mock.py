"""Mock Vision Provider。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .base import VisionProvider, VisionProviderError

logger = logging.getLogger(__name__)


class MockVisionProvider(VisionProvider):
    """读取本地 JSON 文件返回固定结果。"""

    def __init__(self, mock_result_path: Path) -> None:
        self.mock_result_path = mock_result_path

    async def analyze(
        self,
        image_paths: list[Path],
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> str:
        if not self.mock_result_path.exists():
            raise VisionProviderError(
                f"Mock 结果文件不存在: {self.mock_result_path}"
            )
        text = self.mock_result_path.read_text(encoding="utf-8")
        json.loads(text)  # 验证合法 JSON
        logger.info("MockVisionProvider 返回预设结果")
        return text
