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
    assert summary["progress_label"] == "第 4 步：确认与导出"
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


def test_settings_use_progressive_disclosure_and_user_language(user_client: TestClient):
    response = user_client.get("/settings")

    assert response.status_code == 200
    for label in ("AI识别服务", "当前模型", "测试连接", "OCR引擎", "运行系统检查"):
        assert label in response.text
    assert response.text.count('<details class="advanced-settings">') == 1
    assert '<details class="advanced-settings" open>' not in response.text
    assert "<pre" not in response.text
    assert "/static/settings.js" in response.text


def test_settings_show_version_and_safe_update_entry(user_client: TestClient):
    response = user_client.get("/settings")

    assert response.status_code == 200
    assert "版本与更新" in response.text
    assert "检查最新稳定版" in response.text
    assert 'data-check-update="/api/updates/stable"' in response.text


def test_stable_update_api_uses_published_release_metadata(
    user_client: TestClient, monkeypatch
):
    import lite_app.updates as updates

    monkeypatch.setattr(
        updates,
        "_fetch_releases",
        lambda: [
            {
                "tag_name": "v1.0.2",
                "draft": False,
                "prerelease": False,
                "html_url": "https://github.com/liumingyang-maker/daily-record-ocr-lite/releases/tag/v1.0.2",
            }
        ],
    )

    response = user_client.get("/api/updates/stable")

    assert response.status_code == 200
    assert response.json()["latest_version"] == "1.0.2"
    assert response.json()["update_available"] is True


def test_setup_is_five_chinese_stages_without_developer_labels(user_client: TestClient):
    response = user_client.get("/setup")

    assert response.status_code == 200
    for heading in (
        "检查运行环境",
        "配置 AI 识别",
        "测试 AI 连接",
        "测试本地 OCR",
        "开始使用",
    ):
        assert heading in response.text
    assert "Step" not in response.text
    assert "Preset" not in response.text
    assert ">tier<" not in response.text
    assert ">Device<" not in response.text


def test_setup_offers_non_destructive_existing_data_import(user_client: TestClient):
    response = user_client.get("/setup")

    assert response.status_code == 200
    assert "导入现有数据" in response.text
    assert 'data-import-data="/api/desktop/import-data"' in response.text
    assert 'data-model-status="/api/setup/models/status"' in response.text
    assert 'data-install-models="/api/setup/models/install"' in response.text
    assert "下载并校验 OCR 模型" in response.text


def test_existing_data_import_returns_only_safe_counts(
    user_client: TestClient, monkeypatch, tmp_path: Path
):
    import lite_app.main as main

    source = tmp_path / "old" / "data"
    (source / "jobs" / "job-1").mkdir(parents=True)
    (source / "jobs" / "job-1" / "job.json").write_text("{}", encoding="utf-8")
    (source / "secrets.env").write_text("VISION_API_KEY=private-test", encoding="utf-8")
    monkeypatch.setattr(main, "DATA_ROOT", tmp_path / "desktop")

    response = user_client.post(
        "/api/desktop/import-data",
        json={"source_path": str(source), "confirm_non_empty": False},
    )

    assert response.status_code == 200
    assert response.json()["copied_file_counts"] == {"jobs": 1, "secrets": 1}
    assert "private-test" not in response.text


def test_model_status_reports_download_required_without_auto_downloading(
    user_client: TestClient, monkeypatch, tmp_path: Path
):
    import lite_app.main as main

    monkeypatch.setattr(main, "DATA_ROOT", tmp_path / "desktop")

    response = user_client.get("/api/setup/models/status")

    assert response.status_code == 200
    assert response.json()["status"] == "DOWNLOAD_REQUIRED"
    assert response.json()["ready_count"] == 0
    assert not (tmp_path / "desktop" / "models" / "downloads").exists()


def test_error_categories_have_actionable_user_messages():
    presentation = importlib.import_module("lite_app.presentation")

    timeout = presentation.present_error("TIMEOUT", http_status=None, request_id="req-1")
    assert timeout["message"] == "AI 识别服务响应超时"
    assert "连接" in timeout["next_action"]
    assert timeout["advanced"]["request_id"] == "req-1"
