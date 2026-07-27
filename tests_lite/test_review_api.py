from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lite_app.final_result import FinalResultService
from lite_app.settings import SettingsService
from lite_app.storage import JobStorage
from tests_lite.review_fixtures import make_review_final


@pytest.fixture
def review_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jobs_dir = tmp_path / "jobs"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOBS_DIR", str(jobs_dir))
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(data_dir / "knowledge.sqlite3"))
    monkeypatch.setenv("DEMO_MODE", "true")

    from lite_app import main
    from lite_app.config import clear_config_cache

    clear_config_cache()
    monkeypatch.setattr(main, "_get_settings", lambda: SettingsService(data_dir))
    storage = JobStorage(jobs_dir)
    job = storage.create_job()
    job["images"] = [{"source": "source/a.jpg"}]
    job["status"] = "REVIEW_REQUIRED"
    storage.save_job(job)
    final = make_review_final(job["id"])
    FinalResultService(storage.get_job_dir(job["id"])).save(final)
    with TestClient(main.app) as client:
        yield client, storage, job["id"]
    clear_config_cache()


def test_review_api_edits_and_confirms_a_whole_formula(review_client):
    client, _storage, job_id = review_client
    response = client.get(f"/api/jobs/{job_id}/review")
    assert response.status_code == 200
    view = response.json()
    formula = view["groups"][0]["formulas"][0]
    assert formula["date_pending"] is True
    assert formula["blocking_message"].endswith("材料数量需要确认")

    response = client.patch(
        f"/api/jobs/{job_id}/review/formulas/{formula['id']}",
        json={"version": view["version"], "record_date": "2026-07-27"},
    )
    assert response.status_code == 200
    version = response.json()["version"]
    response = client.patch(
        f"/api/jobs/{job_id}/review/formulas/{formula['id']}/materials/material_001",
        json={"version": version, "amount": "60"},
    )
    assert response.status_code == 200
    version = response.json()["version"]

    response = client.post(
        f"/api/jobs/{job_id}/review/formulas/{formula['id']}/confirm",
        json={"version": version},
    )
    assert response.status_code == 200
    assert response.json()["confirmed"] is True
    refreshed = client.get(f"/api/jobs/{job_id}/review").json()
    assert refreshed["summary"]["needs_confirmation"] == 0


def test_review_api_requires_explicit_formula_delete_confirmation(review_client):
    client, _storage, job_id = review_client
    view = client.get(f"/api/jobs/{job_id}/review").json()
    formula_id = view["groups"][0]["formulas"][0]["id"]

    response = client.request(
        "DELETE",
        f"/api/jobs/{job_id}/review/formulas/{formula_id}",
        json={"version": view["version"], "confirmed": False},
    )
    assert response.status_code == 422
    assert "确认删除" in response.json()["detail"]


def test_review_api_supports_business_structure_lifecycle_and_undo(review_client):
    client, storage, job_id = review_client
    view = client.get(f"/api/jobs/{job_id}/review").json()
    group_id = view["groups"][0]["id"]

    saved = client.patch(
        f"/api/jobs/{job_id}/review/groups/{group_id}",
        json={"version": view["version"], "customer": "联创", "product": "G30A"},
    ).json()
    created = client.post(
        f"/api/jobs/{job_id}/review/groups/{group_id}/formulas",
        json={"version": saved["version"]},
    ).json()
    formula_id = created["formula_id"]

    first = client.post(
        f"/api/jobs/{job_id}/review/formulas/{formula_id}/materials",
        json={"version": created["version"], "name": "PA66", "amount": "60", "unit": "kg"},
    ).json()
    second = client.post(
        f"/api/jobs/{job_id}/review/formulas/{formula_id}/materials",
        json={"version": first["version"], "name": "色粉", "amount": "1", "unit": "kg"},
    ).json()
    reordered = client.post(
        f"/api/jobs/{job_id}/review/formulas/{formula_id}/materials/reorder",
        json={
            "version": second["version"],
            "material_ids": [second["material_id"], first["material_id"]],
        },
    ).json()

    process = client.post(
        f"/api/jobs/{job_id}/review/formulas/{formula_id}/process",
        json={"version": reordered["version"], "name": "温度", "value": "260", "unit": "℃"},
    ).json()
    updated = client.patch(
        f"/api/jobs/{job_id}/review/formulas/{formula_id}/process/{process['parameter_id']}",
        json={"version": process["version"], "value": "265"},
    ).json()
    deleted = client.request(
        "DELETE",
        f"/api/jobs/{job_id}/review/formulas/{formula_id}/process/{process['parameter_id']}",
        json={"version": updated["version"]},
    ).json()
    restored = client.post(
        f"/api/jobs/{job_id}/review/undo", json={"version": deleted["version"]}
    ).json()
    assert restored["saved"] is True

    deleted = client.request(
        "DELETE",
        f"/api/jobs/{job_id}/review/formulas/{formula_id}/materials/{first['material_id']}",
        json={"version": restored["version"]},
    ).json()
    restored = client.post(
        f"/api/jobs/{job_id}/review/undo", json={"version": deleted["version"]}
    ).json()
    removed = client.request(
        "DELETE",
        f"/api/jobs/{job_id}/review/formulas/{formula_id}",
        json={"version": restored["version"], "confirmed": True},
    )
    assert removed.status_code == 200
    final = FinalResultService(storage.get_job_dir(job_id)).load()
    assert len(final["pages"][0]["product_sections"][0]["formulas"]) == 1


def test_finalize_appends_knowledge_writes_receipt_and_enters_ready(review_client):
    client, storage, job_id = review_client
    job = storage.get_job(job_id)
    job.update(
        {
            "demo_mode": False,
            "recognition_run_id": "review-run",
            "final_result_run_id": "review-run",
            "ocr_engine": {"effective_provider": "paddleocr_v6", "loaded": True},
            "vision_engine": {
                "provider": "openai_compatible",
                "model": "qwen3.7-plus",
                "healthy": True,
            },
        }
    )
    storage.save_job(job)
    service = FinalResultService(storage.get_job_dir(job_id))
    final = service.load()
    final["recognition_run_id"] = "review-run"
    service.replace(final)

    view = client.get(f"/api/jobs/{job_id}/review").json()
    formula = view["groups"][0]["formulas"][0]
    saved = client.patch(
        f"/api/jobs/{job_id}/review/formulas/{formula['id']}",
        json={"version": view["version"], "record_date": "2026-07-27"},
    ).json()
    saved = client.patch(
        f"/api/jobs/{job_id}/review/formulas/{formula['id']}/materials/material_001",
        json={"version": saved["version"], "amount": "60"},
    ).json()
    confirmed = client.post(
        f"/api/jobs/{job_id}/review/formulas/{formula['id']}/confirm",
        json={"version": saved["version"]},
    ).json()

    response = client.post(f"/api/jobs/{job_id}/finalize")

    assert response.status_code == 200
    assert response.json()["status"] == "READY"
    assert response.json()["receipt"]["formula_count"] == 1
    assert (storage.get_job_dir(job_id) / "review" / "finalization.json").exists()
    assert storage.get_job(job_id)["status"] == "READY"
    assert confirmed["confirmed"] is True


def test_job_page_is_business_review_workspace_and_old_result_redirects(review_client):
    client, _storage, job_id = review_client

    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200
    assert "确认这条配方" in page.text
    assert "字段ID" not in page.text
    assert "确认所有字段" not in page.text
    assert "VLM" not in page.text
    assert "BBox" not in page.text

    old = client.get(f"/jobs/{job_id}/result", follow_redirects=False)
    assert old.status_code == 303
    assert old.headers["location"] == f"/jobs/{job_id}#review"


def test_review_evidence_route_verifies_manifest_hash_and_falls_back(review_client):
    client, storage, job_id = review_client
    job_dir = storage.get_job_dir(job_id)
    source = job_dir / "source" / "a.jpg"
    crop = job_dir / "review" / "evidence" / "formula.jpg"
    source.parent.mkdir(parents=True, exist_ok=True)
    crop.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), "white").save(source)
    Image.new("RGB", (400, 300), "white").save(crop)
    formula_id = make_review_final(job_id)["pages"][0]["product_sections"][0][
        "formulas"
    ][0]["formula_id"]
    manifest = {
        "schema_version": 1,
        "formulas": {
            formula_id: {
                "source_path": "source/a.jpg",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "crop_path": "review/evidence/formula.jpg",
                "crop_sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
            }
        },
    }
    (job_dir / "review" / "evidence_regions.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    view = client.get(f"/api/jobs/{job_id}/review").json()
    evidence = view["groups"][0]["formulas"][0]["evidence"]
    assert evidence["image_url"].endswith(f"/review/evidence/{formula_id}")
    assert evidence["full_image_url"].endswith("source/a.jpg")
    response = client.get(evidence["image_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"

    crop.write_bytes(b"tampered")
    assert client.get(evidence["image_url"]).status_code == 404
    fallback = client.get(f"/api/jobs/{job_id}/review").json()["groups"][0][
        "formulas"
    ][0]["evidence"]
    assert fallback["image_url"] == fallback["full_image_url"]
