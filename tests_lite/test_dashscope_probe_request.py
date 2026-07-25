"""DashScope probe request compatibility contracts."""

from __future__ import annotations

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
@pytest.mark.parametrize(
    ("base_url", "model", "configured", "expected"),
    [
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen3.7-plus",
            None,
            False,
        ),
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen3.7-plus",
            True,
            True,
        ),
        (
            "https://vision.example.com/v1",
            "qwen3.7-plus",
            None,
            True,
        ),
    ],
)
async def test_provider_controls_environment_proxy_usage(
    monkeypatch,
    tmp_path,
    base_url,
    model,
    configured,
    expected,
):
    captured_client_kwargs = {}
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"marker":"VISION-7319"}'}}
                ]
            },
        )

    def async_client_spy(**kwargs):
        captured_client_kwargs.update(kwargs)
        return real_async_client(**kwargs)

    monkeypatch.setattr(
        "lite_app.vision.openai_compatible.httpx.AsyncClient",
        async_client_spy,
    )
    image_path = tmp_path / "probe.png"
    Image.new("RGB", (10, 10), "white").save(image_path)
    config = {
        "base_url": base_url,
        "endpoint": "/chat/completions",
        "api_key": "test-key",
        "model": model,
    }
    if configured is not None:
        config["trust_env"] = configured
    provider = OpenAICompatibleVisionProvider(
        config,
        _transport=httpx.MockTransport(handler),
    )

    await provider.analyze(
        [image_path],
        "Return only JSON.",
        'Read the image and return JSON: {"marker":"value"}.',
        {"type": "object"},
    )

    assert captured_client_kwargs["trust_env"] is expected
