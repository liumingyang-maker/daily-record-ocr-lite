from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lite_app.final_result import FinalResultService
from lite_app.settings import SettingsService
from lite_app.storage import JobStorage
from tests_lite.review_fixtures import make_review_final


@pytest.fixture
def review_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    assert formula["blocking_message"].endswith("缺少日期")

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
