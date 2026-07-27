"""OpenAI Chat Completions 兼容 Vision Provider。"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from .base import (
    VisionConfigurationError,
    VisionConnectionError,
    VisionProvider,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleVisionProvider(VisionProvider):
    """OpenAI Chat Completions 兼容 Provider。"""

    def __init__(self, config: dict[str, Any], _transport: Any = None) -> None:
        self.base_url = config.get("base_url", "").rstrip("/")
        endpoint = config.get("endpoint", "/chat/completions")
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        self.url = self.base_url + endpoint
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "")
        self.is_alibaba_qwen37 = (
            (urlparse(self.base_url).hostname or "").lower().endswith(
                ".aliyuncs.com"
            )
            and self.model.lower() == "qwen3.7-plus"
        )
        self.timeout = int(config.get("timeout_seconds", 180))
        if self.is_alibaba_qwen37:
            self.timeout = max(self.timeout, 300)
        self.temperature = config.get("temperature", 0)
        self.image_detail = config.get("image_detail", "high")
        self.use_json_schema = config.get("use_json_schema", False)
        self.schema_name = config.get("schema_name", "handwritten_record")
        self.extra_headers: dict[str, str] = config.get("extra_headers", {})
        self.extra_body: dict[str, Any] = config.get("extra_body", {})
        self._transport = _transport

        if not self.base_url:
            raise VisionConfigurationError("视觉模型地址 (base_url) 未配置")

    async def analyze(
        self,
        image_paths: list[Path],
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> str:
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": user_prompt}
        ]
        for img_path in image_paths:
            data_url = self._image_to_data_url(img_path)
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

        if self.use_json_schema and json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": self.schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            }

        if self.extra_body:
            body.update(self.extra_body)

        if self.is_alibaba_qwen37:
            body["response_format"] = {"type": "json_object"}
            body["enable_thinking"] = False
            body["stream"] = True

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.extra_headers:
            headers.update(self.extra_headers)

        logger.info("调用视觉模型: %s, 图片数: %d", self.model, len(image_paths))
        start = time.time()

        try:
            client_kwargs: dict[str, Any] = {"timeout": self.timeout}
            if self._transport is not None:
                client_kwargs["transport"] = self._transport
            async with httpx.AsyncClient(**client_kwargs) as client:
                if self.is_alibaba_qwen37:
                    async with client.stream(
                        "POST",
                        self.url,
                        json=body,
                        headers=headers,
                    ) as resp:
                        elapsed = time.time() - start
                        logger.info(
                            "模型响应头耗时: %.1f秒, 状态码: %d",
                            elapsed,
                            resp.status_code,
                        )
                        if resp.status_code < 200 or resp.status_code >= 300:
                            await resp.aread()
                            self._raise_http_error(resp)
                        if "text/event-stream" in resp.headers.get(
                            "content-type", ""
                        ):
                            return await self._extract_stream_content(resp)
                        await resp.aread()
                else:
                    resp = await client.post(
                        self.url,
                        json=body,
                        headers=headers,
                    )
        except httpx.TimeoutException:
            raise VisionConnectionError(
                f"视觉模型接口超时（{self.timeout}秒），请检查模型服务是否运行。"
            )
        except httpx.ConnectError:
            raise VisionConnectionError(
                f"无法连接视觉模型服务: {self.base_url}，请检查地址是否正确。"
            )
        except Exception as e:
            raise VisionConnectionError(f"请求视觉模型失败: {e}")

        elapsed = time.time() - start
        logger.info("模型响应耗时: %.1f秒, 状态码: %d", elapsed, resp.status_code)

        if resp.status_code < 200 or resp.status_code >= 300:
            self._raise_http_error(resp)

        try:
            data = resp.json()
        except Exception:
            raise VisionConnectionError(
                f"视觉模型返回了非法 JSON 响应: {resp.text[:300]}"
            )

        return self._extract_content(data)

    @staticmethod
    def _raise_http_error(resp: httpx.Response) -> None:
        body_text = resp.text[:500]
        if resp.status_code == 401:
            raise VisionConnectionError(
                "视觉模型接口返回 HTTP 401，请检查 API Key。"
                f"响应: {body_text}"
            )
        raise VisionConnectionError(
            f"视觉模型接口返回 HTTP {resp.status_code}。响应: {body_text}"
        )

    @staticmethod
    async def _extract_stream_content(resp: httpx.Response) -> str:
        fragments: list[str] = []
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise VisionConnectionError(
                    "视觉模型流式响应包含非法 JSON 事件。"
                ) from exc
            choices = event.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            content = delta.get("content", "")
            if isinstance(content, str):
                fragments.append(content)
        result = "".join(fragments)
        if not result:
            raise VisionConnectionError("视觉模型流式响应未包含 content。")
        return result

    def _extract_content(self, data: dict[str, Any]) -> str:
        try:
            choices = data["choices"]
            message = choices[0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise VisionConnectionError(
                f"视觉模型响应格式不符合预期: {e}。"
                f"响应: {json.dumps(data, ensure_ascii=False)[:500]}"
            )

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if texts:
                return "\n".join(texts)

        raise VisionConnectionError(
            f"无法从模型响应中提取文本内容。"
            f"响应: {json.dumps(data, ensure_ascii=False)[:500]}"
        )

    def _image_to_data_url(self, image_path: Path) -> str:
        data = image_path.read_bytes()
        if self.is_alibaba_qwen37:
            with Image.open(io.BytesIO(data)) as image:
                if max(image.size) > 1024:
                    image = image.convert("RGB")
                    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    output = io.BytesIO()
                    image.save(
                        output,
                        format="JPEG",
                        quality=70,
                        optimize=True,
                    )
                    data = output.getvalue()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
