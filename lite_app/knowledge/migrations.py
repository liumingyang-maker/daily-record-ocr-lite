"""Non-destructive SQLite migrations for dated formula history."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..date_values import parse_record_date

V2_VERSION = 2
V3_VERSION = 3
V4_VERSION = 4
V2_COLUMNS = {
    "formula_no": "TEXT",
    "record_date": "TEXT",
    "confirmed_at": "TEXT",
    "source_job_id": "TEXT",
    "source_formula_id": "TEXT",
    "source_image_index": "INTEGER",
    "revision_of_id": "INTEGER REFERENCES formulas(id)",
}
V3_COLUMNS = {
    "source_order": "INTEGER",
    "date_status": "TEXT",
    "notes_raw": "TEXT",
    "deleted_at": "TEXT",
}
V4_COLUMNS = {
    "record_date_raw": "TEXT",
}


def apply_migrations(connection: sqlite3.Connection, db_path: Path) -> Path | None:
    """Apply every pending migration and return one pre-migration backup."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    backup_path: Path | None = None
    if not _migration_applied(connection, V2_VERSION):
        backup_path = _backup_if_legacy_data(
            connection,
            db_path,
            version=V2_VERSION,
        )
        _apply_v2(connection)
    if not _migration_applied(connection, V3_VERSION):
        if backup_path is None:
            backup_path = _backup_if_legacy_data(
                connection,
                db_path,
                version=V3_VERSION,
            )
        _apply_v3(connection)
    if not _migration_applied(connection, V4_VERSION):
        if backup_path is None:
            backup_path = _backup_if_legacy_data(
                connection,
                db_path,
                version=V4_VERSION,
            )
        _apply_v4(connection)
    connection.commit()
    return backup_path


def _apply_v2(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "formulas")
    for name, declaration in V2_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE formulas ADD COLUMN {name} {declaration}"
            )
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


def _apply_v3(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "formulas")
    for name, declaration in V3_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE formulas ADD COLUMN {name} {declaration}"
            )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS formula_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            formula_id INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            cell_range TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(formula_id, source_path, sheet_name, cell_range),
            FOREIGN KEY (formula_id) REFERENCES formulas(id)
        );

        CREATE TABLE IF NOT EXISTS formula_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            formula_id INTEGER NOT NULL,
            formula_source_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('tight', 'context')),
            relative_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            UNIQUE(formula_source_id, kind),
            FOREIGN KEY (formula_id) REFERENCES formulas(id),
            FOREIGN KEY (formula_source_id) REFERENCES formula_sources(id)
        );

        CREATE TABLE IF NOT EXISTS lexicon_terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_type TEXT NOT NULL CHECK(
                term_type IN ('customer', 'product', 'material', 'process', 'note_phrase')
            ),
            standard_value TEXT NOT NULL,
            normalized_value TEXT NOT NULL,
            source_quality TEXT NOT NULL CHECK(
                source_quality IN ('reference', 'candidate', 'confirmed')
            ),
            enabled INTEGER NOT NULL DEFAULT 1,
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            accepted_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(term_type, normalized_value)
        );

        CREATE TABLE IF NOT EXISTS lexicon_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            status TEXT NOT NULL CHECK(
                status IN ('observed', 'approved', 'rejected')
            ),
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            accepted_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            customer_context TEXT NOT NULL DEFAULT '',
            product_context TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(term_id, normalized_alias, customer_context, product_context),
            FOREIGN KEY (term_id) REFERENCES lexicon_terms(id)
        );

        CREATE TABLE IF NOT EXISTS lexicon_context_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_id INTEGER NOT NULL,
            customer_context TEXT NOT NULL DEFAULT '',
            product_context TEXT NOT NULL DEFAULT '',
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            accepted_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(term_id, customer_context, product_context),
            FOREIGN KEY (term_id) REFERENCES lexicon_terms(id)
        );

        CREATE TABLE IF NOT EXISTS lexicon_cooccurrences (
            left_term_id INTEGER NOT NULL,
            right_term_id INTEGER NOT NULL,
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(left_term_id, right_term_id),
            FOREIGN KEY (left_term_id) REFERENCES lexicon_terms(id),
            FOREIGN KEY (right_term_id) REFERENCES lexicon_terms(id)
        );

        CREATE TABLE IF NOT EXISTS lexicon_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            formula_id TEXT NOT NULL,
            field_id TEXT NOT NULL,
            field_type TEXT NOT NULL,
            original_value TEXT NOT NULL,
            suggested_value TEXT NOT NULL,
            final_value TEXT NOT NULL,
            decision TEXT NOT NULL,
            customer_context TEXT NOT NULL DEFAULT '',
            product_context TEXT NOT NULL DEFAULT '',
            score REAL,
            margin REAL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS legacy_import_runs (
            run_id TEXT PRIMARY KEY,
            batch_sha256 TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS import_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            start_row INTEGER NOT NULL,
            end_row INTEGER NOT NULL,
            reason TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
            created_at TEXT NOT NULL,
            UNIQUE(run_id, source_path, sheet_name, start_row, end_row, reason),
            FOREIGN KEY (run_id) REFERENCES legacy_import_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS import_exclusions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            start_row INTEGER NOT NULL,
            end_row INTEGER NOT NULL,
            reason TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(run_id, source_path, sheet_name, start_row, end_row, reason),
            FOREIGN KEY (run_id) REFERENCES legacy_import_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_formula_sources_formula
        ON formula_sources(formula_id);
        CREATE INDEX IF NOT EXISTS idx_formula_evidence_formula
        ON formula_evidence(formula_id);
        CREATE INDEX IF NOT EXISTS idx_lexicon_terms_type_value
        ON lexicon_terms(term_type, normalized_value);
        CREATE INDEX IF NOT EXISTS idx_lexicon_alias_lookup
        ON lexicon_aliases(normalized_alias, status);
        CREATE INDEX IF NOT EXISTS idx_lexicon_context
        ON lexicon_context_stats(customer_context, product_context);
        CREATE INDEX IF NOT EXISTS idx_import_candidates_status
        ON import_candidates(status, reason);
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (V3_VERSION, datetime.now(UTC).isoformat()),
    )


def _apply_v4(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "formulas")
    for name, declaration in V4_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE formulas ADD COLUMN {name} {declaration}"
            )

    rows = connection.execute(
        "SELECT id, record_date, record_date_raw FROM formulas"
    ).fetchall()
    for formula_id, record_date, record_date_raw in rows:
        raw = str(record_date_raw if record_date_raw is not None else record_date or "")
        parsed = parse_record_date(raw)
        connection.execute(
            """
            UPDATE formulas
            SET record_date_raw = ?, record_date = ?, date_status = ?
            WHERE id = ?
            """,
            (parsed.raw, parsed.sort_value, parsed.status, formula_id),
        )
    connection.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (V4_VERSION, datetime.now(UTC).isoformat()),
    )


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
    connection: sqlite3.Connection,
    db_path: Path,
    *,
    version: int,
) -> Path | None:
    if not db_path.exists() or not _table_has_rows(connection, "formulas"):
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / (
        f"knowledge-before-v{version}-{timestamp}.sqlite3"
    )
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
