"""Pipeline 模块测试。"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lite_app.pipeline import (
    PipelineError,
    build_prompts,
    extract_json,
    validate_result,
    analyze_job,
)
from lite_app.image_utils import ImageProcessError
from lite_app.config import load_schema_config


class TestExtractJson:
    def test_pure_json(self):
        text = '{"page_heading": "test", "records": [], "warnings": []}'
        result = extract_json(text)
        assert result["page_heading"] == "test"

    def test_json_code_block(self):
        text = '```json\n{"page_heading": "test", "records": [], "warnings": []}\n```'
        result = extract_json(text)
        assert result["page_heading"] == "test"

    def test_json_with_surrounding_text(self):
        text = '以下是识别结果：\n{"page_heading": "hello", "records": [], "warnings": []}\n希望对你有帮助。'
        result = extract_json(text)
        assert result["page_heading"] == "hello"

    def test_invalid_json_raises(self):
        with pytest.raises(PipelineError, match="无法从模型响应中解析"):
            extract_json("this is not json at all")

    def test_top_level_array_rejected(self):
        with pytest.raises(PipelineError, match="数组"):
            extract_json('[{"a": 1}]')

    def test_json_in_middle(self):
        text = 'Some text before {"page_heading": "mid", "records": [], "warnings": []} and after'
        result = extract_json(text)
        assert result["page_heading"] == "mid"

    def test_code_block_without_json_tag(self):
        text = '```\n{"page_heading": "x", "records": [], "warnings": []}\n```'
        result = extract_json(text)
        assert result["page_heading"] == "x"


class TestValidateResult:
    @pytest.fixture
    def schema(self):
        config = load_schema_config()
        return config["schema"]

    def test_valid_result(self, schema):
        result = {
            "page_heading": "test",
            "records": [
                {
                    "source_image_indexes": [1],
                    "record_date": "24.7.10",
                    "title": "配方",
                    "materials": [
                        {"name": "PA66", "amount": "60", "unit": "kg", "confidence": 0.95}
                    ],
                    "process_parameters": [],
                    "notes": "",
                    "confidence": 0.9,
                    "warnings": [],
                }
            ],
            "warnings": [],
        }
        errors = validate_result(result, schema)
        assert errors == []

    def test_missing_field(self, schema):
        result = {"page_heading": "test", "records": []}
        errors = validate_result(result, schema)
        assert len(errors) > 0
        assert any("warnings" in e for e in errors)

    def test_confidence_out_of_range(self, schema):
        result = {
            "page_heading": "",
            "records": [
                {
                    "source_image_indexes": [1],
                    "record_date": "",
                    "title": "",
                    "materials": [
                        {"name": "x", "amount": "1", "unit": "", "confidence": 1.2}
                    ],
                    "process_parameters": [],
                    "notes": "",
                    "confidence": 0.5,
                    "warnings": [],
                }
            ],
            "warnings": [],
        }
        errors = validate_result(result, schema)
        assert len(errors) > 0
        assert any("confidence" in e for e in errors)

    def test_error_includes_path(self, schema):
        result = {
            "page_heading": "",
            "records": [
                {
                    "source_image_indexes": [1],
                    "record_date": "",
                    "title": "",
                    "materials": [
                        {"name": "x", "amount": "1", "unit": "", "confidence": 2.0}
                    ],
                    "process_parameters": [],
                    "notes": "",
                    "confidence": 0.5,
                    "warnings": [],
                }
            ],
            "warnings": [],
        }
        errors = validate_result(result, schema)
        assert any("records.0.materials.0.confidence" in e for e in errors)


class TestBuildPrompts:
    def test_build_prompts_returns_tuple(self):
        config = load_schema_config()
        system, user, schema = build_prompts(config)
        assert isinstance(system, str)
        assert isinstance(user, str)
        assert isinstance(schema, dict)
        assert "JSON" in user
        assert "不要" in user or "看不清" in user


class TestAnalyzeJob:
    @pytest.mark.asyncio
    async def test_mock_full_flow(self, storage, sample_image):
        """使用 mock provider 完成完整分析流程。"""
        job = storage.create_job(rotation="0")
        job_id = job["id"]
        # 保存图片
        content = sample_image.read_bytes()
        img_info = storage.save_upload(job_id, 1, "test.jpg", content)
        job["images"].append(img_info)
        storage.save_job(job)

        result_job = await analyze_job(job_id, storage)
        assert result_job["status"] in ("READY", "NEED_REVIEW")
        # 验证结果文件存在
        loaded = storage.load_result(job_id)
        assert loaded is not None
        assert "page_heading" in loaded

    @pytest.mark.asyncio
    async def test_failed_on_bad_image(self, storage, tmp_path):
        """非图片文件导致 FAILED。"""
        job = storage.create_job(rotation="0")
        job_id = job["id"]
        # 保存一个非图片文件
        bad_content = b"not an image"
        img_info = storage.save_upload(job_id, 1, "bad.jpg", bad_content)
        job["images"].append(img_info)
        storage.save_job(job)

        with pytest.raises(ImageProcessError):
            await analyze_job(job_id, storage)

        updated = storage.get_job(job_id)
        assert updated["status"] == "FAILED"
        assert updated["error"]
