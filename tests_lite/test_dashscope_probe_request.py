"""DashScope probe request compatibility contracts."""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from lite_app.vision.openai_compatible import OpenAICompatibleVisionProvider


def test_qwen37_plus_uses_at_least_five_minute_timeout():
    provider = OpenAICompatibleVisionProvider(
        {
            "base_url": (
                "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            "endpoint": "/chat/completions",
            "api_key": "test-key",
            "model": "qwen3.7-plus",
            "timeout_seconds": 120,
        }
    )

    assert provider.timeout == 300


def test_qwen37_plus_preserves_longer_timeout():
    provider = OpenAICompatibleVisionProvider(
        {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen3.7-plus",
            "timeout_seconds": 420,
        }
    )

    assert provider.timeout == 420


def test_other_models_keep_configured_timeout():
    provider = OpenAICompatibleVisionProvider(
        {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-plus",
            "timeout_seconds": 120,
        }
    )

    assert provider.timeout == 120


def test_qwen37_plus_on_other_hosts_keeps_configured_timeout():
    provider = OpenAICompatibleVisionProvider(
        {
            "base_url": "https://vision.example.com/v1",
            "model": "qwen3.7-plus",
            "timeout_seconds": 120,
        }
    )

    assert provider.timeout == 120


@pytest.mark.asyncio
async def test_qwen37_plus_uses_dashscope_json_object_mode(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"marker":"VISION-7319"}'}}
                ]
            },
        )

    image_path = tmp_path / "probe.png"
    Image.new("RGB", (10, 10), "white").save(image_path)
    provider = OpenAICompatibleVisionProvider(
        {
            "base_url": (
                "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            "endpoint": "/chat/completions",
            "api_key": "test-key",
            "model": "qwen3.7-plus",
            "use_json_schema": False,
        },
        _transport=httpx.MockTransport(handler),
    )

    await provider.analyze(
        [image_path],
        "Return only JSON.",
        'Read the image and return JSON: {"marker":"value"}.',
        {"type": "object"},
    )

    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["enable_thinking"] is False
    prompts = json.dumps(captured["body"]["messages"], ensure_ascii=False)
    assert "JSON" in prompts


@pytest.mark.asyncio
async def test_qwen37_plus_downscales_large_images_before_upload(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":true}'}}]},
        )

    image_path = tmp_path / "large.jpg"
    Image.new("RGB", (2000, 1200), "white").save(
        image_path,
        format="JPEG",
        quality=95,
    )
    provider = OpenAICompatibleVisionProvider(
        {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "endpoint": "/chat/completions",
            "api_key": "test-key",
            "model": "qwen3.7-plus",
        },
        _transport=httpx.MockTransport(handler),
    )

    await provider.analyze(
        [image_path],
        "Return only JSON.",
        "Describe the image as JSON.",
        {"type": "object"},
    )

    data_url = captured["body"]["messages"][1]["content"][1][
        "image_url"
    ]["url"]
    encoded = data_url.split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as uploaded:
        assert max(uploaded.size) == 1024
        assert uploaded.format == "JPEG"


@pytest.mark.asyncio
async def test_qwen37_plus_streams_and_assembles_json_content(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"{\\"marker\\":"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"\\"VISION-7319\\"}"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    image_path = tmp_path / "probe.png"
    Image.new("RGB", (10, 10), "white").save(image_path)
    provider = OpenAICompatibleVisionProvider(
        {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "endpoint": "/chat/completions",
            "api_key": "test-key",
            "model": "qwen3.7-plus",
        },
        _transport=httpx.MockTransport(handler),
    )

    content = await provider.analyze(
        [image_path],
        "Return only JSON.",
        "Read the image and return JSON.",
        {"type": "object"},
    )

    assert captured["body"]["stream"] is True
    assert json.loads(content) == {"marker": "VISION-7319"}
