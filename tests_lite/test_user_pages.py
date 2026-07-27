from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lite_app.settings import SettingsService
from lite_app.storage import JobStorage


def test_internal_statuses_have_user_language():
    presentation = importlib.import_module("lite_app.presentation")

    assert presentation.user_status("REVIEW_REQUIRED")["label"] == "需要确认"
    assert presentation.user_status("FAILED_SCHEMA")["label"] == "识别失败"
    assert presentation.user_status("DEGRADED")["next_action"] == "查看原因并重试"


def test_job_summary_prefers_business_identity():
    presentation = importlib.import_module("lite_app.presentation")

    summary = presentation.present_job(
        {
            "id": "20260727-000000-abcdef",
            "status": "REVIEW_REQUIRED",
            "created_at": "2026-07-27T00:00:00",
            "images": [{}, {}],
            "business_summary": {
                "customers": ["联创"],
                "products": ["G30A"],
                "date_min": "2026-07-01",
                "date_max": "2026-07-26",
            },
        }
    )

    assert summary["customer"] == "联创"
    assert summary["product"] == "G30A"
    assert summary["date_range"] == "2026-07-01 至 2026-07-26"
    assert summary["next_action"] == "继续确认"
    assert summary["advanced"]["job_id"] == "20260727-000000-abcdef"


def test_stored_job_derives_business_summary_without_mutating_job(tmp_path: Path):
    presentation = importlib.import_module("lite_app.presentation")
    from lite_app.grouping.models import (
        BusinessEntities,
        CompanyGroup,
        EvidenceField,
        Formula,
        ProductGroup,
    )
    from lite_app.grouping.storage import save_business_entities

    job = {
        "id": "20260727-000000-abcdef",
        "status": "REVIEW_REQUIRED",
        "images": [{}],
    }
    save_business_entities(
        tmp_path,
        BusinessEntities(
            job_id=job["id"],
            company_groups=[CompanyGroup(display_name="联创")],
            product_groups=[ProductGroup(display_name="G30A")],
            formulas=[Formula(record_date=EvidenceField(standard_value="2026-07-27"))],
        ),
    )

    summary = presentation.present_stored_job(job, tmp_path)

    assert summary["customer"] == "联创"
    assert summary["product"] == "G30A"
    assert summary["date_range"] == "2026-07-27"
    assert "business_summary" not in job


@pytest.fixture
def user_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jobs_dir = tmp_path / "jobs"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOBS_DIR", str(jobs_dir))
    monkeypatch.setenv("DEMO_MODE", "true")

    from lite_app import main
    from lite_app.config import clear_config_cache

    clear_config_cache()
    monkeypatch.setattr(main, "_get_settings", lambda: SettingsService(data_dir))
    storage = JobStorage(jobs_dir)
    job = storage.create_job()
    job["status"] = "REVIEW_REQUIRED"
    job["provider"] = "openai_compatible"
    job["model"] = "qwen3.7-plus"
    job["images"] = [{"source": "source/page.png"}]
    job["business_summary"] = {
        "customers": ["联创"],
        "products": ["G30A"],
        "date_min": "2026-07-27",
        "date_max": "2026-07-27",
    }
    storage.save_job(job)

    with TestClient(main.app) as client:
        yield client
    clear_config_cache()


def test_navigation_uses_user_tasks(user_client: TestClient):
    response = user_client.get("/")

    assert response.status_code == 200
    assert "开始识别" in response.text
    assert "识别记录" in response.text
    assert "配方知识库" in response.text
    assert "设置" in response.text


def test_upload_page_has_per_image_controls(user_client: TestClient):
    response = user_client.get("/")

    assert response.status_code == 200
    assert 'id="upload-preview"' in response.text
    assert 'name="rotation_manifest"' in response.text
    assert '/static/upload.js' in response.text


def test_recognition_records_hide_provider_from_primary_table(user_client: TestClient):
    response = user_client.get("/jobs")

    assert response.status_code == 200
    assert "客户" in response.text
    assert "产品/牌号" in response.text
    assert "配方日期" in response.text
    assert "继续确认" in response.text
    assert "Provider / Model" not in response.text
    assert "qwen3.7-plus" not in response.text
