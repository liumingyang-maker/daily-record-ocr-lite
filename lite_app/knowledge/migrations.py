"""Non-destructive SQLite migrations for dated formula history."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

V2_VERSION = 2
V2_COLUMNS = {
    "formula_no": "TEXT",
    "record_date": "TEXT",
    "confirmed_at": "TEXT",
    "source_job_id": "TEXT",
    "source_formula_id": "TEXT",
    "source_image_index": "INTEGER",
    "revision_of_id": "INTEGER REFERENCES formulas(id)",
}


def apply_migrations(connection: sqlite3.Connection, db_path: Path) -> Path | None:
    """Apply v2 once and return the pre-migration backup path, if created."""
    if _migration_applied(connection, V2_VERSION):
        return None

    backup_path = _backup_if_legacy_data(connection, db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    columns = _columns(connection, "formulas")
    for name, declaration in V2_COLUMNS.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE formulas ADD COLUMN {name} {declaration}")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS formula_process_parameters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            formula_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            name TEXT NOT NULL,
            value TEXT NOT NULL,
            unit TEXT,
            FOREIGN KEY (formula_id) REFERENCES formulas(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_imports (
            source_job_id TEXT PRIMARY KEY,
            final_result_sha256 TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_formulas_source
        ON formulas(source_job_id, source_formula_id)
        WHERE source_job_id IS NOT NULL AND source_formula_id IS NOT NULL
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_formulas_history ON formulas(customer_id, product_id, record_date)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_formula_process_formula ON formula_process_parameters(formula_id)"
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (V2_VERSION, datetime.now(UTC).isoformat()),
    )
    connection.commit()
    return backup_path


def _migration_applied(connection: sqlite3.Connection, version: int) -> bool:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not table:
        return False
    return (
        connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
        ).fetchone()
        is not None
    )


def _backup_if_legacy_data(
    connection: sqlite3.Connection, db_path: Path
) -> Path | None:
    if not db_path.exists() or not _table_has_rows(connection, "formulas"):
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"knowledge-before-v2-{timestamp}.sqlite3"
    backup = sqlite3.connect(backup_path)
    try:
        connection.backup(backup)
    finally:
        backup.close()
    return backup_path


def _table_has_rows(connection: sqlite3.Connection, table: str) -> bool:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return False
    return connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
