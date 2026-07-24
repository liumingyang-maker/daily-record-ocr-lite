"""v1 Web/API fail-closed and FinalResult acceptance contracts."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image

from lite_app.final_result import FinalResultService, project_final_result
from lite_app.jobs import TaskQueue
from lite_app.readiness import iter_final_fields
from lite_app.settings import SettingsService
from lite_app.storage import JobStorage, write_json_atomic


@pytest.fixture
def v1_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jobs_dir = tmp_path / "jobs"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOBS_DIR", str(jobs_dir))
    monkeypatch.setenv("DEMO_MODE", "true")

    from lite_app import main
    from lite_app.config import clear_config_cache

    clear_config_cache()
    monkeypatch.setattr(main, "_get_settings", lambda: SettingsService(data_dir))
    with TestClient(main.app) as client:
        yield client, JobStorage(jobs_dir), data_dir
    clear_config_cache()


def _strict_result() -> dict:
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "config" / "mock_result.json").read_text("utf-8"))


def _image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _create_final(storage: JobStorage) -> tuple[str, str]:
    job = storage.create_job()
    job["demo_mode"] = False
    job["images"] = [{"source": "source/source_01_test.jpg"}]
    job["recognition_run_id"] = "web-test-run"
    job["ocr_engine"] = {
        "effective_provider": "paddleocr_v6",
        "loaded": True,
    }
    job["vision_engine"] = {
        "provider": "openai_compatible",
        "model": "vision-model",
        "healthy": True,
    }
    structured = _strict_result()
    formula = structured["pages"][0]["product_sections"][0]["formulas"][0]
    formula["formula_id"] = f"{job['id']}__page_001__formula_001"
    final = project_final_result(job["id"], structured, {"fields": []})
    final["recognition_run_id"] = "web-test-run"
    for _, field in iter_final_fields(final):
        field["status"] = "MANUAL_CONFIRMED"
        field["review_status"] = "MANUAL_CONFIRMED"
    FinalResultService(storage.get_job_dir(job["id"])).replace(final)
    job["final_result_run_id"] = "web-test-run"
    job["status"] = "READY"
    storage.save_job(job)
    amount_id = (
        f"{job['id']}__page_001__formula_001__material_001__amount"
    )
    return job["id"], amount_id


def _create_numeric_conflict(storage: JobStorage) -> tuple[str, str]:
    job = storage.create_job()
    job["demo_mode"] = False
    job["images"] = [{"source": "source/source_01_test.jpg"}]
    job["recognition_run_id"] = "web-conflict-run"
    job["ocr_engine"] = {
        "effective_provider": "paddleocr_v6",
        "loaded": True,
    }
    job["vision_engine"] = {
        "provider": "openai_compatible",
        "model": "vision-model",
        "healthy": True,
    }
    structured = _strict_result()
    formula = structured["pages"][0]["product_sections"][0]["formulas"][0]
    formula["formula_id"] = f"{job['id']}__page_001__formula_001"
    formula["materials"][0]["amount"]["value"] = "0.5"
    amount_id = f"{formula['formula_id']}__material_001__amount"
    fusion = {
        "schema_version": "fusion-v1",
        "fields": [
            {
                "field_id": amount_id,
                "field_type": "amount",
                "final_value": "0.15",
                "final_confidence": 0.94,
                "final_source": "conflict",
                "status": "CONFLICT",
                "reasons": ["数值冲突：OCR=0.15, VLM=0.5"],
                "candidates": [
                    {
                        "value": "0.5",
                        "source": "vlm",
                        "confidence": 0.87,
                        "evidence": ["p1_t005"],
                    },
                    {
                        "value": "0.15",
                        "source": "ocr_base",
                        "confidence": 0.94,
                        "evidence": ["p1_t005"],
                    },
                ],
            }
        ],
    }
    job_dir = storage.get_job_dir(job["id"])
    write_json_atomic(job_dir / "vision" / "structured_result.json", structured)
    write_json_atomic(job_dir / "fusion" / "result.json", fusion)
    final = project_final_result(job["id"], structured, fusion)
    final["recognition_run_id"] = "web-conflict-run"
    for field_id, field in iter_final_fields(final):
        if field_id != amount_id:
            field["status"] = "MANUAL_CONFIRMED"
            field["review_status"] = "MANUAL_CONFIRMED"
    FinalResultService(job_dir).replace(final)
    job["final_result_run_id"] = "web-conflict-run"
    job["status"] = "REVIEW_REQUIRED"
    storage.save_job(job)
    return job["id"], amount_id


def test_unconfigured_install_blocks_job_creation(
    v1_client, monkeypatch: pytest.MonkeyPatch
):
    client, _, _ = v1_client
    monkeypatch.setenv("DEMO_MODE", "false")

    from lite_app.config import clear_config_cache

    monkeypatch.setenv("VISION_PROVIDER", "")
    monkeypatch.setenv("VISION_BASE_URL", "")
    monkeypatch.setenv("VISION_MODEL", "")
    monkeypatch.setenv("VISION_API_KEY", "")
    clear_config_cache()
    response = client.post(
        "/jobs",
        files=[("files", ("page.png", _image_bytes(), "image/png"))],
    )
    assert response.status_code == 409
    assert "SETUP_REQUIRED" in response.json()["detail"]


def test_settings_secret_is_write_only(v1_client):
    client, _, _ = v1_client
    response = client.put(
        "/api/settings/vision",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model": "vision-model",
            "api_key": "top-secret-value",
        },
    )
    assert response.status_code == 200
    serialized = json.dumps(response.json())
    assert "top-secret-value" not in serialized

    public = client.get("/api/settings/public")
    assert public.status_code == 200
    assert "top-secret-value" not in public.text
    assert public.json()["vision"]["api_key_configured"] is True


def test_setup_and_settings_pages_are_real_configuration_pages(v1_client):
    client, _, _ = v1_client
    setup = client.get("/setup")
    settings = client.get("/settings")
    assert setup.status_code == 200
    assert settings.status_code == 200
    assert "视觉模型" in setup.text
    assert "Python" in setup.text
    assert "PaddleOCR" in setup.text
    assert "Ollama" in setup.text
    assert "阿里云百炼" in setup.text
    assert "可能产生少量费用" in setup.text
    assert "系统已就绪" in setup.text
    assert "OCR" in settings.text
    assert "/api/settings/vision" in settings.text
    assert "/api/settings/test-vision" in settings.text


def test_demo_banner_is_visible_and_connection_test_is_explicit(v1_client):
    client, _, _ = v1_client
    index = client.get("/")
    assert "演示模式" in index.text
    assert "不代表真实识别" in index.text

    response = client.post("/api/settings/test-vision", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "DEMO_MODE"


def test_vision_connection_test_reports_capabilities(
    v1_client, monkeypatch: pytest.MonkeyPatch
):
    client, _, _ = v1_client
    from lite_app import main, pipeline_v2

    class FakeVisionProvider:
        async def analyze(self, *_args, **_kwargs):
            return '{"marker": "VISION-7319"}'

    monkeypatch.setattr(main, "_demo_enabled", lambda: False)
    monkeypatch.setattr(
        pipeline_v2,
        "build_vision_provider",
        lambda _config: FakeVisionProvider(),
    )
    response = client.post("/api/settings/test-vision", json={})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "OK"
    assert result["http_status"] == 200
    assert result["vision_capability"] is True
    assert result["json_response_capability"] is True
    assert result["strict_json_capability"] is True
    assert result["response_preview"] == '{"marker": "VISION-7319"}'
    assert result["error_category"] is None
    assert isinstance(result["latency_ms"], int)


def test_vision_connection_test_accepts_markdown_json(
    v1_client, monkeypatch: pytest.MonkeyPatch
):
    client, _, _ = v1_client
    from lite_app import main, pipeline_v2

    class FakeVisionProvider:
        async def analyze(self, *_args, **_kwargs):
            return '```json\n{"marker":"VISION-7319"}\n```'

    monkeypatch.setattr(main, "_demo_enabled", lambda: False)
    monkeypatch.setattr(
        pipeline_v2,
        "build_vision_provider",
        lambda _config: FakeVisionProvider(),
    )
    result = client.post("/api/settings/test-vision", json={}).json()
    assert result["status"] == "OK"
    assert result["vision_capability"] is True
    assert result["json_response_capability"] is True
    assert result["strict_json_capability"] is False
    assert result["error_category"] is None
    assert len(result["response_preview"]) <= 500


def test_vision_connection_test_separates_wrong_marker_from_json_failure(
    v1_client, monkeypatch: pytest.MonkeyPatch
):
    client, _, _ = v1_client
    from lite_app import main, pipeline_v2

    class FakeVisionProvider:
        async def analyze(self, *_args, **_kwargs):
            return '{"marker":"VISION-0000"}'

    monkeypatch.setattr(main, "_demo_enabled", lambda: False)
    monkeypatch.setattr(
        pipeline_v2,
        "build_vision_provider",
        lambda _config: FakeVisionProvider(),
    )
    result = client.post("/api/settings/test-vision", json={}).json()
    assert result["status"] == "FAILED_VISION_CAPABILITY"
    assert result["vision_capability"] is False
    assert result["json_response_capability"] is True
    assert result["strict_json_capability"] is True
    assert result["error_category"] == "VISION_CAPABILITY"


def test_ocr_connection_test_reports_tokens_and_overlay(
    v1_client, monkeypatch: pytest.MonkeyPatch
):
    client, _, _ = v1_client
    from lite_app.ocr import manager as manager_module
    from lite_app.ocr import overlay as overlay_module

    class FakeManager:
        def configure(self, _config):
            return None

        async def recognize_async(self, _image_path):
            return SimpleNamespace(
                provider="paddleocr_v6",
                model="PP-OCRv6_medium",
                tokens=[SimpleNamespace(text="PA66", confidence=0.99)],
                elapsed_ms=18,
            )

        def get_status(self):
            return {
                "det_model": "PP-OCRv6_medium_det",
                "rec_model": "PP-OCRv6_medium_rec",
            }

    def fake_overlay(_image, _page, output):
        output.write_bytes(b"jpeg")
        return output

    monkeypatch.setattr(manager_module, "OCRModelManager", FakeManager)
    monkeypatch.setattr(overlay_module, "generate_overlay", fake_overlay)
    response = client.post("/api/settings/test-ocr", json={})
    assert response.status_code == 200
    result = response.json()
    assert result["token_count"] == 1
    assert result["token_preview"][0]["text"] == "PA66"
    assert result["models"]["det_model"] == "PP-OCRv6_medium_det"
    assert client.get(result["overlay_url"]).status_code == 200


def test_settings_write_rejects_nonlocal_or_form_requests(v1_client):
    client, _, _ = v1_client
    external = client.put(
        "/api/settings/vision",
        json={"model": "x"},
        headers={"host": "evil.example"},
    )
    assert external.status_code == 403

    form = client.put(
        "/api/settings/vision",
        content="model=x",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert form.status_code == 415


def test_final_result_manual_value_is_excel_source(v1_client):
    client, storage, _ = v1_client
    job_id, amount_id = _create_numeric_conflict(storage)
    job_dir = storage.get_job_dir(job_id)

    before = FinalResultService(job_dir).load()
    before_amount = before["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["amount"]
    assert before_amount["status"] == "CONFLICT"
    assert {item["value"] for item in before_amount["candidates"]} == {
        "0.15",
        "0.5",
    }

    response = client.post(
        f"/api/jobs/{job_id}/fields/{amount_id}",
        json={"value": "0.15", "source": "manual"},
    )
    assert response.status_code == 200
    final = FinalResultService(job_dir).load()
    amount = final["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["amount"]
    assert amount["value"] == "0.15"
    assert amount["status"] == "MANUAL_CONFIRMED"
    fusion = json.loads((job_dir / "fusion" / "result.json").read_text("utf-8"))
    assert fusion["fields"][0]["final_value"] == "0.15"
    assert fusion["fields"][0]["status"] == "MANUAL_CONFIRMED"
    vision = json.loads(
        (job_dir / "vision" / "structured_result.json").read_text("utf-8")
    )
    vision_amount = vision["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["amount"]["value"]
    assert vision_amount == "0.5"

    response = client.post(f"/api/jobs/{job_id}/export")
    assert response.status_code == 200
    workbook = load_workbook(
        job_dir / response.json()["filename"],
        data_only=True,
    )
    assert workbook["配方明细"]["G2"].value == "0.15"
    assert workbook["配方明细"]["G2"].value != "0.5"


def test_candidate_button_resolves_value_from_final_result(v1_client):
    client, storage, _ = v1_client
    job_id, amount_id = _create_numeric_conflict(storage)

    response = client.post(
        f"/api/jobs/{job_id}/fields/{amount_id}",
        json={"value": "", "source": "ocr"},
    )

    assert response.status_code == 200
    assert response.json()["value"] == "0.15"
    final = FinalResultService(storage.get_job_dir(job_id)).load()
    amount = final["pages"][0]["product_sections"][0]["formulas"][0]["materials"][0][
        "amount"
    ]
    assert amount["value"] == "0.15"
    assert amount["status"] == "MANUAL_CONFIRMED"


@pytest.mark.parametrize("broken_content", [None, "{not-json"])
def test_confirm_fails_closed_without_valid_final_result(
    v1_client, broken_content: str | None
):
    client, storage, _ = v1_client
    job = storage.create_job()
    if broken_content is not None:
        path = storage.get_job_dir(job["id"]) / "review" / "final_result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(broken_content, encoding="utf-8")

    response = client.post(f"/api/jobs/{job['id']}/confirm")
    assert response.status_code == 409
    assert response.json()["detail"]
    assert storage.get_job(job["id"])["status"] != "READY"


@pytest.mark.asyncio
async def test_task_queue_rebinds_after_stop():
    seen: list[str] = []

    async def handler(job_id: str) -> None:
        seen.append(job_id)

    queue = TaskQueue()
    queue.set_handler(handler)
    await queue.start()
    await queue.submit("first")
    await queue._queue.join()
    first_queue = queue._queue
    await queue.stop()

    await queue.start()
    await queue.submit("second")
    await queue._queue.join()
    await queue.stop()

    assert seen == ["first", "second"]
    assert queue._queue is not first_queue


def test_full_result_replacement_rejects_invalid_schema(v1_client):
    client, storage, _ = v1_client
    job_id, _ = _create_final(storage)
    invalid = copy.deepcopy(_strict_result())
    invalid.pop("pages")
    response = client.post(f"/api/jobs/{job_id}/result", json=invalid)
    assert response.status_code == 422
    assert storage.get_job(job_id)["status"] == "FAILED_SCHEMA"


def test_job_status_changes_are_audited(tmp_path: Path):
    storage = JobStorage(tmp_path / "jobs")
    job = storage.create_job()
    job["status"] = "PREPROCESSING"
    storage.save_job(job)
    job["status"] = "FAILED_SCHEMA"
    storage.save_job(job)

    events = json.loads(
        (
            storage.get_job_dir(job["id"]) / "review" / "job_events.json"
        ).read_text("utf-8")
    )
    transitions = [
        (event.get("from_status"), event["to_status"]) for event in events
    ]
    assert all("reason" in event for event in events)
    assert (None, "UPLOADED") in transitions
    assert ("UPLOADED", "PREPROCESSING") in transitions
    assert ("PREPROCESSING", "FAILED_SCHEMA") in transitions


def test_formula_number_edit_updates_final_result_not_projection_only(v1_client):
    client, storage, _ = v1_client
    job_id, _ = _create_final(storage)
    final = FinalResultService(storage.get_job_dir(job_id)).load()
    formula_id = final["pages"][0]["product_sections"][0]["formulas"][0][
        "formula_id"
    ]

    response = client.patch(
        f"/api/jobs/{job_id}/formulas/{formula_id}/number",
        json={"formula_no_raw": "⑨"},
    )
    assert response.status_code == 200
    reloaded = FinalResultService(storage.get_job_dir(job_id)).load()
    assert (
        reloaded["pages"][0]["product_sections"][0]["formulas"][0]["formula_no"]
        == "⑨"
    )
