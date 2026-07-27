from __future__ import annotations

import sqlite3

import pytest

from lite_app.final_result import FinalResultService
from lite_app.grouping.service import final_result_fingerprint
from lite_app.knowledge.history import KnowledgeHistory
from lite_app.review_editor import ReviewEditor
from lite_app.review_state import ReviewStateStore, confirm_formula
from tests_lite.review_fixtures import make_review_final


def _confirmed_job(tmp_path, job_id: str, date: str, amount: str = "60"):
    job_dir = tmp_path / job_id
    final = make_review_final(job_id)
    formula = final["pages"][0]["product_sections"][0]["formulas"][0]
    formula["record_date"]["value"] = date
    formula["record_date"]["status"] = "AUTO_ACCEPT"
    formula["materials"][0]["amount"]["value"] = amount
    formula["materials"][0]["amount"]["status"] = "AUTO_ACCEPT"
    FinalResultService(job_dir).save(final)
    editor = ReviewEditor(job_dir)
    store = ReviewStateStore(job_dir)
    confirm_formula(editor, store, formula["formula_id"], editor.load()["updated_at"])
    return (
        {"id": job_id, "images": [{"source": "source/a.jpg"}]},
        editor.load(),
        store.confirmed_hashes(editor.load()),
    )


def test_history_appends_dates_idempotently_and_links_revision(tmp_path):
    history = KnowledgeHistory(tmp_path / "knowledge.sqlite3")
    job1, final1, hashes1 = _confirmed_job(tmp_path, "job-one", "2026-07-27", "60")

    receipt1 = history.append_confirmed_job(job1, final1, hashes1)

    assert receipt1["final_result_sha256"] == final_result_fingerprint(final1)
    assert history.append_confirmed_job(job1, final1, hashes1) == receipt1
    assert history.timeline("联创", "G30A")[0]["record_date"] == "2026-07-27"

    job2, final2, hashes2 = _confirmed_job(tmp_path, "job-two", "2026-07-28", "62")
    receipt2 = history.append_confirmed_job(job2, final2, hashes2)
    timeline = history.timeline("联创", "G30A")
    assert [item["record_date"] for item in timeline] == ["2026-07-27", "2026-07-28"]
    assert receipt2["formula_ids"] != receipt1["formula_ids"]
    assert timeline[1]["revision_of_id"] == timeline[0]["id"]


def test_history_rolls_back_every_row_on_insert_failure(tmp_path, monkeypatch):
    history = KnowledgeHistory(tmp_path / "knowledge.sqlite3")
    job, final, hashes = _confirmed_job(tmp_path, "job-fail", "2026-07-27")

    def fail(*_args, **_kwargs):
        raise RuntimeError("controlled write failure")

    monkeypatch.setattr(history, "_insert_formula", fail)
    with pytest.raises(RuntimeError, match="controlled"):
        history.append_confirmed_job(job, final, hashes)

    connection = sqlite3.connect(tmp_path / "knowledge.sqlite3")
    assert connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM formulas").fetchone()[0] == 0
    connection.close()


def test_history_rejects_missing_or_stale_confirmation_hash(tmp_path):
    history = KnowledgeHistory(tmp_path / "knowledge.sqlite3")
    job, final, hashes = _confirmed_job(tmp_path, "job-stale", "2026-07-27")
    formula_id = next(iter(hashes))

    with pytest.raises(ValueError, match="确认"):
        history.append_confirmed_job(job, final, {})
    hashes[formula_id] = "stale"
    with pytest.raises(ValueError, match="确认"):
        history.append_confirmed_job(job, final, hashes)


def test_history_keeps_unknown_date_as_formal_pending_metadata(tmp_path):
    history = KnowledgeHistory(tmp_path / "knowledge.sqlite3")
    job, final, hashes = _confirmed_job(
        tmp_path,
        "job-unknown-date",
        "",
    )

    receipt = history.append_confirmed_job(job, final, hashes)
    detail = history.formula_detail(receipt["formula_ids"][0])

    assert detail["record_date"] == ""
    assert detail["date_status"] == "UNKNOWN"


def test_history_preserves_handwritten_date_and_exposes_sort_value(tmp_path):
    history = KnowledgeHistory(tmp_path / "knowledge.sqlite3")
    job, final, hashes = _confirmed_job(tmp_path, "job-handwritten-date", "24.7.19")

    receipt = history.append_confirmed_job(job, final, hashes)
    detail = history.formula_detail(receipt["formula_ids"][0])

    assert detail["record_date"] == "24.7.19"
    assert detail["record_date_sort"] == "2024-07-19"
    assert detail["date_status"] == "KNOWN"


def test_timeline_keeps_unknown_source_record_between_known_neighbors(tmp_path):
    history = KnowledgeHistory(tmp_path / "knowledge.sqlite3")
    connection = history.database._get_conn()
    customer_id = connection.execute(
        "INSERT INTO customers (name) VALUES ('联创')"
    ).lastrowid
    product_id = connection.execute(
        "INSERT INTO products (customer_id, name) VALUES (?, 'G30A')",
        (customer_id,),
    ).lastrowid
    rows = [
        ("配方1", "24.1.1", "2024-01-01", "KNOWN", 1),
        ("配方2", "", None, "UNKNOWN", 2),
        ("配方3", "24.3.1", "2024-03-01", "KNOWN", 3),
    ]
    for formula_no, raw, sort_value, status, source_order in rows:
        connection.execute(
            """
            INSERT INTO formulas (
                customer_id, product_id, title, formula_no,
                record_date_raw, record_date, date_status, source_order,
                source_job_id, confirmed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'same-source', '2026-07-27T00:00:00+00:00')
            """,
            (
                customer_id,
                product_id,
                formula_no,
                formula_no,
                raw,
                sort_value,
                status,
                source_order,
            ),
        )
    connection.commit()

    timeline = history.timeline("联创", "G30A")

    assert [item["formula_no"] for item in timeline] == ["配方1", "配方2", "配方3"]
    assert [item["record_date"] for item in timeline] == ["24.1.1", "", "24.3.1"]
