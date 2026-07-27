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


def test_v4_migration_preserves_raw_dates_and_derives_safe_sort_values(tmp_path):
    db_path = tmp_path / "knowledge.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES (2, 'before'), (3, 'before');
        CREATE TABLE formulas (
            id INTEGER PRIMARY KEY,
            title TEXT,
            customer_id INTEGER,
            product_id INTEGER,
            record_date TEXT,
            date_status TEXT
        );
        INSERT INTO formulas VALUES (1, '合法原文', NULL, NULL, '24.7.19', 'KNOWN');
        INSERT INTO formulas VALUES (2, '不可解析原文', NULL, NULL, '日期不清', 'KNOWN');
        """
    )
    connection.commit()
    connection.close()

    database = KnowledgeDB(db_path)
    database.initialize()
    database.close()

    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT id, record_date_raw, record_date, date_status FROM formulas ORDER BY id"
    ).fetchall()
    applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = 4"
    ).fetchone()
    connection.close()

    assert rows == [
        (1, "24.7.19", "2024-07-19", "KNOWN"),
        (2, "日期不清", None, "UNPARSED"),
    ]
    assert applied == (1,)
    assert len(list((tmp_path / "backups").glob("knowledge-before-v4-*.sqlite3"))) == 1
