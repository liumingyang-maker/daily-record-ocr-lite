from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lite_app.storage import JobStorage
from tests_lite.knowledge_fixtures import seed_dated_history


@pytest.fixture
def knowledge_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jobs_dir = tmp_path / "jobs"
    db_path = tmp_path / "knowledge.sqlite3"
    monkeypatch.setenv("JOBS_DIR", str(jobs_dir))
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(db_path))
    storage = JobStorage(jobs_dir)
    source_jobs = []
    for _ in range(2):
        job = storage.create_job()
        job["images"] = [{"source": "source/page.jpg"}]
        storage.save_job(job)
        source_jobs.append(job["id"])
    formula_ids = seed_dated_history(db_path, tuple(source_jobs))

    from lite_app import main

    with TestClient(main.app) as client:
        yield client, formula_ids, source_jobs


def test_knowledge_tree_detail_and_comparison(knowledge_client):
    client, (older, newer), source_jobs = knowledge_client

    tree = client.get("/api/knowledge/tree?q=G30A").json()
    product = tree["customers"][0]["products"][0]
    assert product["formula_count"] == 2
    assert [item["record_date"] for item in product["formulas"]] == [
        "2026-07-27",
        "2026-07-28",
    ]

    detail = client.get(f"/api/knowledge/formulas/{newer}").json()
    assert detail["record_date"] == "2026-07-28"
    assert detail["materials"][0]["amount"] == "62"
    assert detail["evidence_image_url"].startswith(f"/jobs/{source_jobs[1]}/files/")

    comparison = client.get(f"/api/knowledge/compare?left={older}&right={newer}").json()
    assert comparison["materials"]["PA66"]["before"] == "60"
    assert comparison["materials"]["PA66"]["after"] == "62"
    assert comparison["process"]["温度"]["before"] == "260"
    assert comparison["process"]["温度"]["after"] == "265"


def test_knowledge_page_is_customer_product_date_timeline(knowledge_client):
    client, _formula_ids, _source_jobs = knowledge_client

    page = client.get("/knowledge")

    assert page.status_code == 200
    assert "客户 / 产品 / 日期" in page.text
    assert "比较配方" in page.text
    assert "物料字典" in page.text
    assert '<details class="material-dictionary">' in page.text
    assert "/static/knowledge.js" in page.text
