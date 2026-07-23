"""Provider 模块测试。"""

import json
import pytest
import httpx
from pathlib import Path

from lite_app.providers import (
    MockProvider,
    OpenAICompatibleProvider,
    VisionProviderError,
    build_provider,
)


class TestMockProvider:
    @pytest.mark.asyncio
    async def test_returns_valid_json(self, tmp_path):
        mock_file = tmp_path / "mock.json"
        mock_file.write_text(
            '{"page_heading": "mock", "records": [], "warnings": []}',
            encoding="utf-8",
        )
        provider = MockProvider(mock_file)
        result = await provider.analyze([], "sys", "user", {})
        data = json.loads(result)
        assert data["page_heading"] == "mock"

    @pytest.mark.asyncio
    async def test_missing_file_raises(self, tmp_path):
        provider = MockProvider(tmp_path / "nonexistent.json")
        with pytest.raises(VisionProviderError, match="不存在"):
            await provider.analyze([], "sys", "user", {})


class TestOpenAICompatibleProvider:
    def _make_config(self, **overrides):
        cfg = {
            "base_url": "http://localhost:9999/v1",
            "endpoint": "/chat/completions",
            "api_key": "test-key-123",
            "model": "test-model",
            "timeout_seconds": 10,
            "temperature": 0,
            "image_detail": "high",
            "use_json_schema": False,
            "schema_name": "test",
            "extra_headers": {},
            "extra_body": {},
        }
        cfg.update(overrides)
        return cfg

    def _make_response(self, content):
        return {"choices": [{"message": {"content": content}}]}

    def _make_test_image(self, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        img_path = tmp_path / "test.jpg"
        img.save(img_path, format="JPEG")
        return img_path

    @pytest.mark.asyncio
    async def test_request_body_with_images(self, tmp_path):
        """验证多图 data URL 请求体。"""
        img_path = self._make_test_image(tmp_path)
        captured = {}

        def handler(request: httpx.Request):
            captured["body"] = json.loads(request.content)
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json=self._make_response('{"page_heading": "", "records": [], "warnings": []}'),
            )

        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleProvider(self._make_config(), _transport=transport)
        await provider.analyze([img_path], "sys prompt", "user prompt", {})

        body = captured["body"]
        assert body["model"] == "test-model"
        assert body["temperature"] == 0
        messages = body["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        # user content 应包含 text 和 image_url
        user_content = messages[1]["content"]
        assert user_content[0]["type"] == "text"
        assert user_content[1]["type"] == "image_url"
        assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    @pytest.mark.asyncio
    async def test_authorization_header(self, tmp_path):
        """验证 Authorization 头。"""
        img_path = self._make_test_image(tmp_path)
        captured = {}

        def handler(request: httpx.Request):
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json=self._make_response('{"page_heading": "", "records": [], "warnings": []}'),
            )

        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleProvider(
            self._make_config(api_key="my-secret"), _transport=transport
        )
        await provider.analyze([img_path], "sys", "user", {})
        assert captured["headers"]["authorization"] == "Bearer my-secret"

    @pytest.mark.asyncio
    async def test_extra_headers_and_body(self, tmp_path):
        """验证 extra headers/body 合并。"""
        img_path = self._make_test_image(tmp_path)
        captured = {}

        def handler(request: httpx.Request):
            captured["body"] = json.loads(request.content)
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json=self._make_response('{"page_heading": "", "records": [], "warnings": []}'),
            )

        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleProvider(
            self._make_config(
                extra_headers={"X-Custom": "value"},
                extra_body={"custom_param": True},
            ),
            _transport=transport,
        )
        await provider.analyze([img_path], "sys", "user", {})
        assert captured["headers"]["x-custom"] == "value"
        assert captured["body"]["custom_param"] is True

    @pytest.mark.asyncio
    async def test_string_content_response(self, tmp_path):
        """验证字符串 content 响应解析。"""
        img_path = self._make_test_image(tmp_path)

        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json=self._make_response('{"page_heading": "hi", "records": [], "warnings": []}'),
            )

        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleProvider(self._make_config(), _transport=transport)
        result = await provider.analyze([img_path], "sys", "user", {})
        assert "hi" in result

    @pytest.mark.asyncio
    async def test_array_content_response(self, tmp_path):
        """验证数组 content 响应解析。"""
        img_path = self._make_test_image(tmp_path)
        response_data = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": '{"page_heading": "arr", "records": [], "warnings": []}'}
                        ]
                    }
                }
            ]
        }

        def handler(request: httpx.Request):
            return httpx.Response(200, json=response_data)

        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleProvider(self._make_config(), _transport=transport)
        result = await provider.analyze([img_path], "sys", "user", {})
        assert "arr" in result

    @pytest.mark.asyncio
    async def test_http_401_error(self, tmp_path):
        """验证 HTTP 401 错误处理。"""
        img_path = self._make_test_image(tmp_path)

        def handler(request: httpx.Request):
            return httpx.Response(401, text="Unauthorized")

        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleProvider(self._make_config(), _transport=transport)
        with pytest.raises(VisionProviderError, match="401"):
            await provider.analyze([img_path], "sys", "user", {})

    @pytest.mark.asyncio
    async def test_http_500_error(self, tmp_path):
        """验证 HTTP 500 错误处理。"""
        img_path = self._make_test_image(tmp_path)

        def handler(request: httpx.Request):
            return httpx.Response(500, text="Internal Server Error")

        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleProvider(self._make_config(), _transport=transport)
        with pytest.raises(VisionProviderError, match="500"):
            await provider.analyze([img_path], "sys", "user", {})

    @pytest.mark.asyncio
    async def test_unexpected_response_format(self, tmp_path):
        """验证非预期响应格式。"""
        img_path = self._make_test_image(tmp_path)

        def handler(request: httpx.Request):
            return httpx.Response(200, json={"unexpected": "format"})

        transport = httpx.MockTransport(handler)
        provider = OpenAICompatibleProvider(self._make_config(), _transport=transport)
        with pytest.raises(VisionProviderError, match="不符合预期"):
            await provider.analyze([img_path], "sys", "user", {})

    @pytest.mark.asyncio
    async def test_response_format_option(self):
        """验证 use_json_schema 配置。"""
        provider = OpenAICompatibleProvider(
            self._make_config(use_json_schema=True, schema_name="my_schema")
        )
        assert provider.use_json_schema is True
        assert provider.schema_name == "my_schema"

    def test_empty_base_url_raises(self):
        """验证空 base_url 报错。"""
        with pytest.raises(VisionProviderError, match="未配置"):
            OpenAICompatibleProvider(self._make_config(base_url=""))

    def test_url_construction(self):
        """验证 URL 构建。"""
        provider = OpenAICompatibleProvider(self._make_config())
        assert provider.url == "http://localhost:9999/v1/chat/completions"

    def test_url_trailing_slash(self):
        """验证 base_url 尾部斜杠处理。"""
        provider = OpenAICompatibleProvider(
            self._make_config(base_url="http://localhost:9999/v1/")
        )
        assert provider.url == "http://localhost:9999/v1/chat/completions"


class TestBuildProvider:
    def test_build_mock(self):
        provider = build_provider({"provider": "mock", "mock_result": "config/mock_result.json"})
        assert isinstance(provider, MockProvider)

    def test_build_openai_compatible(self):
        cfg = {
            "provider": "openai_compatible",
            "base_url": "http://localhost:1234/v1",
            "endpoint": "/chat/completions",
            "api_key": "",
            "model": "test",
            "timeout_seconds": 30,
            "temperature": 0,
            "image_detail": "high",
            "use_json_schema": False,
            "schema_name": "test",
            "extra_headers": {},
            "extra_body": {},
        }
        provider = build_provider(cfg)
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(VisionProviderError, match="未知"):
            build_provider({"provider": "unknown_provider"})
