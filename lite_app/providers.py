"""视觉模型 Provider 抽象及内置实现。"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from .image_utils import image_to_data_url

logger = logging.getLogger(__name__)


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


class MockProvider(VisionProvider):
    """Mock Provider：读取本地 JSON 文件返回固定结果。"""

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
        # 验证是合法 JSON
        json.loads(text)
        logger.info("MockProvider 返回预设结果")
        return text


class OpenAICompatibleProvider(VisionProvider):
    """OpenAI Chat Completions 兼容 Provider。"""

    def __init__(self, config: dict[str, Any], _transport: Any = None) -> None:
        self.base_url = config.get("base_url", "").rstrip("/")
        endpoint = config.get("endpoint", "/chat/completions")
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        self.url = self.base_url + endpoint
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "")
        self.timeout = config.get("timeout_seconds", 120)
        self.temperature = config.get("temperature", 0)
        self.image_detail = config.get("image_detail", "high")
        self.use_json_schema = config.get("use_json_schema", False)
        self.schema_name = config.get("schema_name", "handwritten_record")
        self.extra_headers: dict[str, str] = config.get("extra_headers", {})
        self.extra_body: dict[str, Any] = config.get("extra_body", {})
        self._transport = _transport  # 测试用

        if not self.base_url:
            raise VisionProviderError("视觉模型地址 (base_url) 未配置")

    async def analyze(
        self,
        image_paths: list[Path],
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> str:
        # 构建 messages
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": user_prompt}
        ]
        # 多图按顺序追加
        for img_path in image_paths:
            data_url = image_to_data_url(img_path)
            user_content.append({
                "type": "image_url",
                "image_url": {"url": data_url, "detail": self.image_detail},
            })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        # 可选 JSON Schema response format
        if self.use_json_schema and json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": self.schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            }

        # 合并 extra_body
        if self.extra_body:
            body.update(self.extra_body)

        # 构建请求头
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.extra_headers:
            headers.update(self.extra_headers)

        logger.info(
            "调用视觉模型: %s, 图片数: %d", self.model, len(image_paths)
        )
        start = time.time()

        try:
            client_kwargs: dict[str, Any] = {"timeout": self.timeout}
            if self._transport is not None:
                client_kwargs["transport"] = self._transport
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(
                    self.url, json=body, headers=headers
                )
        except httpx.TimeoutException:
            raise VisionProviderError(
                f"视觉模型接口超时（{self.timeout}秒），请检查模型服务是否运行。"
            )
        except httpx.ConnectError:
            raise VisionProviderError(
                f"无法连接视觉模型服务: {self.base_url}，请检查地址是否正确。"
            )
        except Exception as e:
            raise VisionProviderError(f"请求视觉模型失败: {e}")

        elapsed = time.time() - start
        logger.info("模型响应耗时: %.1f秒, 状态码: %d", elapsed, resp.status_code)

        if resp.status_code < 200 or resp.status_code >= 300:
            # 截断响应正文
            body_text = resp.text[:500]
            if resp.status_code == 401:
                raise VisionProviderError(
                    f"视觉模型接口返回 HTTP 401，请检查 API Key。响应: {body_text}"
                )
            raise VisionProviderError(
                f"视觉模型接口返回 HTTP {resp.status_code}。响应: {body_text}"
            )

        # 解析响应
        try:
            data = resp.json()
        except Exception:
            raise VisionProviderError(
                f"视觉模型返回了非法 JSON 响应: {resp.text[:300]}"
            )

        return self._extract_content(data)

    def _extract_content(self, data: dict[str, Any]) -> str:
        """从 Chat Completions 响应中提取文本内容。"""
        try:
            choices = data["choices"]
            message = choices[0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise VisionProviderError(
                f"视觉模型响应格式不符合预期: {e}。响应: {json.dumps(data, ensure_ascii=False)[:500]}"
            )

        # content 可能是字符串
        if isinstance(content, str):
            return content

        # content 可能是数组
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            if texts:
                return "\n".join(texts)

        raise VisionProviderError(
            f"无法从模型响应中提取文本内容。响应: {json.dumps(data, ensure_ascii=False)[:500]}"
        )


def build_provider(vision_config: dict[str, Any]) -> VisionProvider:
    """根据配置构建 Provider 实例。"""
    provider_name = vision_config.get("provider", "mock")

    if provider_name == "mock":
        from .config import PROJECT_ROOT

        mock_path_str = vision_config.get("mock_result", "config/mock_result.json")
        mock_path = Path(mock_path_str)
        if not mock_path.is_absolute():
            mock_path = PROJECT_ROOT / mock_path
        return MockProvider(mock_path)

    if provider_name == "openai_compatible":
        return OpenAICompatibleProvider(vision_config)

    raise VisionProviderError(
        f"未知的 Provider: {provider_name}。"
        f"可用: mock, openai_compatible"
    )
