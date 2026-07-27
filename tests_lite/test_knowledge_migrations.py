from __future__ import annotations

import sqlite3

from lite_app.knowledge.database import KnowledgeDB


def test_v2_migration_backs_up_and_preserves_legacy_formula(tmp_path):
    db_path = tmp_path / "knowledge.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE formulas (id INTEGER PRIMARY KEY, title TEXT, customer_id INTEGER, product_id INTEGER)"
    )
    connection.execute("INSERT INTO formulas (title) VALUES (?)", ("旧配方",))
    connection.commit()
    connection.close()

    database = KnowledgeDB(db_path)
    database.initialize()
    database.close()

    connection = sqlite3.connect(db_path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(formulas)")}
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    legacy = connection.execute("SELECT title FROM formulas WHERE id = 1").fetchone()
    connection.close()
    backups = list((tmp_path / "backups").glob("knowledge-before-v2-*.sqlite3"))

    assert len(backups) == 1
    assert legacy[0] == "旧配方"
    assert columns >= {
        "formula_no",
        "record_date",
        "confirmed_at",
        "source_job_id",
        "source_formula_id",
        "source_image_index",
        "revision_of_id",
    }
    assert "formula_process_parameters" in tables

    database = KnowledgeDB(db_path)
    database.initialize()
    database.close()
    assert len(list((tmp_path / "backups").glob("knowledge-before-v2-*.sqlite3"))) == 1
