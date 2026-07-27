from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
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
    evidence_path = (
        db_path.parent
        / "personal_imports"
        / "test"
        / "evidence"
        / "formula-tight.png"
    )
    evidence_path.parent.mkdir(parents=True)
    evidence_bytes = b"\x89PNG\r\n\x1a\nEVIDENCE"
    evidence_path.write_bytes(evidence_bytes)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        INSERT INTO legacy_import_runs (
            run_id, batch_sha256, summary_json, created_at
        ) VALUES ('test-import', 'hash', '{}', ?)
        """,
        (datetime.now(UTC).isoformat(),),
    )
    connection.execute(
        """
        INSERT INTO import_candidates (
            run_id, source_path, sheet_name, start_row, end_row,
            reason, payload_json, status, created_at
        ) VALUES (
            'test-import', '客户/待确认.xlsx', 'G30A', 2, 5,
            'MULTIPLE_DATES', ?,
            'PENDING_REVIEW', ?
        )
        """,
        (
            '{"formula":{"customer":"客户","product":"G30A","formula_label":"配方1","materials":[{"name_raw":"PA66"}]}}',
            datetime.now(UTC).isoformat(),
        ),
    )
    source_id = connection.execute(
        """
        INSERT INTO formula_sources (
            formula_id, source_path, sheet_name, cell_range, created_at
        ) VALUES (?, '客户/历史.xlsx', 'G30A', 'A2:D6', ?)
        """,
        (formula_ids[1], datetime.now(UTC).isoformat()),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO formula_evidence (
            formula_id, formula_source_id, kind, relative_path, sha256
        ) VALUES (?, ?, 'tight', ?, ?)
        """,
        (
            formula_ids[1],
            source_id,
            evidence_path.relative_to(db_path.parent).as_posix(),
            hashlib.sha256(evidence_bytes).hexdigest(),
        ),
    )
    connection.commit()
    connection.close()

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
    assert detail["evidence"][0]["source_path"] == "客户/历史.xlsx"
    evidence = client.get(detail["evidence"][0]["image_url"])
    assert evidence.status_code == 200
    assert evidence.content == b"\x89PNG\r\n\x1a\nEVIDENCE"

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


def test_pending_review_identifies_formula_and_material(knowledge_client):
    client, _formula_ids, _source_jobs = knowledge_client

    pending = client.get("/api/knowledge/pending").json()

    assert pending["total"] == 1
    assert pending["items"][0]["product"] == "G30A"
    assert pending["items"][0]["materials"] == ["PA66"]
