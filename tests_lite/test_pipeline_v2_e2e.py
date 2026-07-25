"""Formal v2 pipeline -> manual review API -> FinalResult Excel acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image

from lite_app.config import load_schema_config
from lite_app.final_result import FinalResultService
from lite_app.ocr.base import OCRPage, OCRToken
from lite_app.storage import JobStorage


def _token(token_id: str, text: str, bbox: list[float]) -> OCRToken:
    return OCRToken(
        id=token_id,
        text=text,
        confidence=0.98,
        polygon=[
            [bbox[0], bbox[1]],
            [bbox[2], bbox[1]],
            [bbox[2], bbox[3]],
            [bbox[0], bbox[3]],
        ],
        bbox=bbox,
        center_x=(bbox[0] + bbox[2]) / 2,
        center_y=(bbox[1] + bbox[3]) / 2,
    )


class RealNamedOCRManager:
    def configure(self, _config):
        return None

    def get_status(self):
        return {
            "loaded": True,
            "configured_provider": "paddleocr_v6",
            "effective_provider": "paddleocr_v6",
            "provider": "paddleocr_v6",
            "tier": "medium",
            "device": "cpu",
            "det_model": "PP-OCRv6_mobile_det",
            "rec_model": "PP-OCRv6_mobile_rec",
        }

    async def recognize_async(self, image_path: Path) -> OCRPage:
        with Image.open(image_path) as image:
            width, height = image.size
        return OCRPage(
            image_index=1,
            width=width,
            height=height,
            tokens=[
                _token("local-name", "PA66", [100, 100, 200, 140]),
                _token("local-amount", "0.15", [100, 180, 180, 220]),
                _token("local-unit", "kg", [200, 180, 250, 220]),
            ],
            average_confidence=0.98,
            provider="paddleocr_v6",
            model="PP-OCRv6_medium",
            elapsed_ms=12,
        )


class VisionResultProvider:
    def __init__(self, result: dict):
        self.result = result
        self.user_prompt: str | None = None

    async def analyze(
        self,
        _image_paths,
        _system_prompt,
        user_prompt,
        _json_schema,
    ):
        self.user_prompt = user_prompt
        return json.dumps(self.result, ensure_ascii=False)


class TestSettings:
    def effective_settings(self):
        return {
            "vision": {
                "provider": "openai_compatible",
                "base_url": "https://example.invalid/v1",
                "endpoint": "/chat/completions",
                "model": "vision-model",
                "api_key": "test-key",
            }
        }


def _vision_result() -> dict:
    return {
        "schema_version": "record-v1",
        "pages": [
            {
                "page_id": "page_001",
                "source_image_index": 1,
                "company": {
                    "raw_value": "测试公司",
                    "standard_value": "测试公司",
                    "confidence": 0.98,
                    "bbox": [0.1, 0.05, 0.4, 0.09],
                    "evidence_token_ids": ["p1_t001"],
                    "match_source": "vlm",
                    "review_status": "AUTO_ACCEPT",
                },
                "product_sections": [
                    {
                        "section_id": "section_001",
                        "product_or_series": {
                            "value": "PA66 系列",
                            "confidence": 0.98,
                            "evidence_token_ids": ["p1_t001"],
                            "bbox": [0.1, 0.1, 0.3, 0.16],
                        },
                        "product_type": "series",
                        "section_bbox": [0.08, 0.08, 0.9, 0.8],
                        "formulas": [
                            {
                                "formula_id": "remote-id-must-be-rewritten",
                                "formula_no": "1",
                                "formula_sequence": 1,
                                "record_date": {
                                    "value": "2026-07-24",
                                    "confidence": 0.98,
                                    "evidence_token_ids": ["p1_t001"],
                                    "bbox": [0.1, 0.18, 0.3, 0.22],
                                },
                                "record_bbox": [0.1, 0.2, 0.32, 0.58],
                                "materials": [
                                    {
                                        "material_id": "remote-material-id",
                                        "name": {
                                            "value": "PA66",
                                            "confidence": 0.98,
                                            "evidence_token_ids": ["p1_t001"],
                                            "bbox": [0.125, 0.25, 0.25, 0.35],
                                        },
                                        "amount": {
                                            "value": "0.5",
                                            "confidence": 0.95,
                                            "evidence_token_ids": ["p1_t002"],
                                            "bbox": [0.125, 0.45, 0.225, 0.55],
                                        },
                                        "unit": {
                                            "value": "kg",
                                            "confidence": 0.98,
                                            "evidence_token_ids": ["p1_t003"],
                                            "bbox": [0.25, 0.45, 0.3125, 0.55],
                                        },
                                        "warnings": [],
                                    }
                                ],
                                "process_parameters": [],
                                "notes": {
                                    "value": "验收记录",
                                    "confidence": 0.98,
                                    "evidence_token_ids": ["p1_t001"],
                                    "bbox": [0.1, 0.6, 0.3, 0.65],
                                },
                                "warnings": [],
                                "confidence": 0.98,
                            }
                        ],
                        "warnings": [],
                    }
                ],
                "warnings": [],
            }
        ],
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_v2_pipeline_conflict_manual_api_and_excel_source(
    tmp_path, monkeypatch
):
    from lite_app import main, pipeline_v2

    storage = JobStorage(tmp_path / "jobs")
    job = storage.create_job()
    image_path = tmp_path / "source.png"
    Image.new("RGB", (800, 400), "white").save(image_path)
    info = storage.save_upload(
        job["id"],
        1,
        image_path.name,
        image_path.read_bytes(),
    )
    job["images"].append(info)
    storage.save_job(job)

    monkeypatch.setattr(pipeline_v2, "_demo_mode", lambda: False)
    monkeypatch.setattr(
        pipeline_v2,
        "load_recognition_config",
        lambda: {
            "ocr": {"enabled": True, "provider": "paddleocr_v6"},
            "cache": {"enabled": False},
        },
    )
    monkeypatch.setattr(
        pipeline_v2, "OCRModelManager", RealNamedOCRManager
    )
    monkeypatch.setattr(
        pipeline_v2, "SettingsService", lambda _path: TestSettings()
    )
    vision_provider = VisionResultProvider(_vision_result())
    monkeypatch.setattr(
        pipeline_v2, "build_vision_provider", lambda _config: vision_provider
    )
    monkeypatch.setattr(pipeline_v2, "_history_candidates", lambda _result: {})

    result = await pipeline_v2.analyze_job_v2(job["id"], storage)
    assert result["status"] == "REVIEW_REQUIRED"
    compact_schema = json.dumps(
        load_schema_config()["schema"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert vision_provider.user_prompt is not None
    assert f"JSON_SCHEMA={compact_schema}" in vision_provider.user_prompt

    final = FinalResultService(storage.get_job_dir(job["id"])).load()
    amount = final["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["amount"]
    assert amount["status"] == "CONFLICT"
    assert {candidate["value"] for candidate in amount["candidates"]} == {
        "0.15",
        "0.5",
    }
    vision = json.loads(
        (
            storage.get_job_dir(job["id"])
            / "vision"
            / "structured_result.json"
        ).read_text(encoding="utf-8")
    )
    assert vision["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["amount"]["value"] == "0.5"

    monkeypatch.setattr(main, "_get_storage", lambda: storage)
    with TestClient(main.app) as client:
        update = client.post(
            f"/api/jobs/{job['id']}/fields/{amount['field_id']}",
            json={"value": "0.15", "source": "manual"},
        )
        assert update.status_code == 200
        assert update.json()["job_status"] == "READY"
        exported = client.post(f"/api/jobs/{job['id']}/export")
        assert exported.status_code == 200

    workbook = load_workbook(
        storage.get_job_dir(job["id"]) / exported.json()["filename"],
        data_only=True,
    )
    assert workbook["配方明细"]["G2"].value == "0.15"
    assert workbook["配方明细"]["G2"].value != "0.5"
