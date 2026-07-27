"""轻量知识库：使用 Python 标准库 sqlite3。"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    standard_name TEXT NOT NULL UNIQUE,
    category TEXT,
    default_unit TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS material_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT,
    source TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(material_id, alias),
    FOREIGN KEY (material_id) REFERENCES materials(id)
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    aliases_json TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER,
    name TEXT NOT NULL,
    aliases_json TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS formulas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER,
    product_id INTEGER,
    title TEXT,
    color TEXT,
    fingerprint TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS formula_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_id INTEGER NOT NULL,
    seq INTEGER,
    material_id INTEGER,
    material_name TEXT,
    amount TEXT,
    normalized_amount REAL,
    unit TEXT,
    FOREIGN KEY (formula_id) REFERENCES formulas(id),
    FOREIGN KEY (material_id) REFERENCES materials(id)
);

CREATE TABLE IF NOT EXISTS correction_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    record_id TEXT,
    field_id TEXT NOT NULL,
    original_field_id TEXT,
    field_type TEXT,
    old_value TEXT,
    new_value TEXT,
    chosen_source TEXT,
    ocr_value TEXT,
    vlm_value TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recognition_cache (
    cache_key TEXT PRIMARY KEY,
    image_hash TEXT NOT NULL,
    stage TEXT NOT NULL,
    model TEXT,
    version TEXT,
    result_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT,
    source TEXT,
    UNIQUE(company_id, alias),
    FOREIGN KEY (company_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS product_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT,
    source TEXT,
    UNIQUE(product_id, alias),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE INDEX IF NOT EXISTS idx_aliases_alias ON material_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_formula_items_formula ON formula_items(formula_id);
CREATE INDEX IF NOT EXISTS idx_corrections_job ON correction_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_cache_hash ON recognition_cache(image_hash);
"""


class KnowledgeDB:
    """知识库数据库管理器。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def initialize(self) -> None:
        """创建表结构。"""
        conn = self._get_conn()
        from .migrations import apply_migrations

        formulas_exist = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='formulas'"
        ).fetchone()
        if formulas_exist:
            apply_migrations(conn, self.db_path)
        conn.executescript(_SCHEMA_SQL)
        apply_migrations(conn, self.db_path)
        correction_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(correction_logs)").fetchall()
        }
        if "original_field_id" not in correction_columns:
            conn.execute("ALTER TABLE correction_logs ADD COLUMN original_field_id TEXT")
        conn.commit()
        logger.info("知识库初始化完成: %s", self.db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ─── 物料操作 ───────────────────────────────────────────

    def add_material(self, standard_name: str, category: str = "", default_unit: str = "") -> int:
        now = datetime.now(UTC).isoformat()
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT OR IGNORE INTO materials (standard_name, category, default_unit, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (standard_name, category, default_unit, now, now),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM materials WHERE standard_name = ?", (standard_name,)
        ).fetchone()
        return row["id"]

    def add_alias(
        self, material_id: int, alias: str, alias_type: str = "ocr_error", source: str = "manual"
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO material_aliases (material_id, alias, alias_type, source) VALUES (?, ?, ?, ?)",
            (material_id, alias, alias_type, source),
        )
        conn.commit()

    def find_material_by_name(self, name: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM materials WHERE standard_name = ?", (name,)).fetchone()
        if row:
            return dict(row)
        # 查别名
        alias_row = conn.execute(
            "SELECT m.* FROM materials m JOIN material_aliases a ON m.id = a.material_id WHERE a.alias = ?",
            (name,),
        ).fetchone()
        if alias_row:
            return dict(alias_row)
        return None

    def get_all_materials(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM materials ORDER BY usage_count DESC").fetchall()
        return [dict(r) for r in rows]

    def get_all_aliases(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT a.*, m.standard_name FROM material_aliases a JOIN materials m ON a.material_id = m.id"
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── 配方操作 ───────────────────────────────────────────

    def add_formula(
        self, title: str, customer_id: int | None = None, product_id: int | None = None
    ) -> int:
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO formulas (title, customer_id, product_id) VALUES (?, ?, ?)",
            (title, customer_id, product_id),
        )
        conn.commit()
        return cur.lastrowid

    def add_formula_item(
        self,
        formula_id: int,
        seq: int,
        material_name: str,
        amount: str,
        unit: str = "",
        material_id: int | None = None,
    ) -> None:
        normalized = None
        try:
            normalized = float(amount)
        except (ValueError, TypeError):
            pass
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO formula_items (formula_id, seq, material_id, material_name, amount, normalized_amount, unit) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (formula_id, seq, material_id, material_name, amount, normalized, unit),
        )
        conn.commit()

    def get_formula_items(self, formula_id: int) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM formula_items WHERE formula_id = ? ORDER BY seq", (formula_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_formulas(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM formulas ORDER BY usage_count DESC").fetchall()
        return [dict(r) for r in rows]

    # ─── 修正日志 ───────────────────────────────────────────

    def add_correction(
        self,
        job_id: str,
        field_id: str,
        field_type: str,
        old_value: str,
        new_value: str,
        chosen_source: str = "manual",
        ocr_value: str = "",
        vlm_value: str = "",
        record_id: str = "",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO correction_logs (job_id, record_id, field_id, field_type, old_value, new_value, chosen_source, ocr_value, vlm_value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                record_id,
                field_id,
                field_type,
                old_value,
                new_value,
                chosen_source,
                ocr_value,
                vlm_value,
                now,
            ),
        )
        conn.commit()

    def get_corrections_for_job(self, job_id: str) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM correction_logs WHERE job_id = ? ORDER BY created_at", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def remap_correction_field_ids(
        self,
        job_id: str,
        field_mapping: dict[str, str],
        record_mapping: dict[str, str] | None = None,
    ) -> None:
        """Keep historical corrections attached after canonical ID migrations."""
        conn = self._get_conn()
        for old_id, new_id in field_mapping.items():
            conn.execute(
                """
                UPDATE correction_logs
                SET original_field_id = COALESCE(original_field_id, field_id),
                    field_id = ?
                WHERE job_id = ? AND field_id = ?
                """,
                (new_id, job_id, old_id),
            )
        for old_id, new_id in (record_mapping or {}).items():
            conn.execute(
                """
                UPDATE correction_logs
                SET record_id = ?
                WHERE job_id = ? AND record_id = ?
                """,
                (new_id, job_id, old_id),
            )
        conn.commit()

    # ─── 缓存 ─────────────────────────────────────────────

    def get_cache(self, cache_key: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM recognition_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        return dict(row) if row else None

    def set_cache(
        self,
        cache_key: str,
        image_hash: str,
        stage: str,
        result_path: str,
        model: str = "",
        version: str = "",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO recognition_cache (cache_key, image_hash, stage, model, version, result_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cache_key, image_hash, stage, model, version, result_path, now),
        )
        conn.commit()

    def invalidate_cache(self, image_hash: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM recognition_cache WHERE image_hash = ?", (image_hash,))
        conn.commit()

    # ─── 公司别名 ─────────────────────────────────────────

    def add_company_alias(
        self, company_id: int, alias: str, alias_type: str = "manual", source: str = "web"
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO company_aliases (company_id, alias, alias_type, source) VALUES (?, ?, ?, ?)",
            (company_id, alias, alias_type, source),
        )
        conn.commit()

    def find_company_by_alias(self, alias: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT c.* FROM customers c JOIN company_aliases a ON c.id = a.company_id WHERE a.alias = ?",
            (alias,),
        ).fetchone()
        return dict(row) if row else None

    # ─── 产品别名 ─────────────────────────────────────────

    def add_product_alias(
        self, product_id: int, alias: str, alias_type: str = "manual", source: str = "web"
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO product_aliases (product_id, alias, alias_type, source) VALUES (?, ?, ?, ?)",
            (product_id, alias, alias_type, source),
        )
        conn.commit()

    def find_product_by_alias(self, alias: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT p.* FROM products p JOIN product_aliases a ON p.id = a.product_id WHERE a.alias = ?",
            (alias,),
        ).fetchone()
        return dict(row) if row else None
