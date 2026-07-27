"""Transactional, append-only customer/product formula history."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..grouping.service import final_result_fingerprint
from ..readiness import validate_final_result_contract
from ..review_state import formula_content_hash
from .database import KnowledgeDB


class KnowledgeHistory:
    def __init__(self, db_path: Path) -> None:
        self.database = KnowledgeDB(db_path)
        self.database.initialize()

    def append_confirmed_job(
        self,
        job: dict[str, Any],
        final: dict[str, Any],
        confirmed_hashes: dict[str, str],
    ) -> dict[str, Any]:
        report = validate_final_result_contract(final)
        if report.issues:
            raise ValueError(f"FinalResult 无效: {report.issues[0].message}")
        job_id = str(job.get("id", ""))
        if not job_id or final.get("job_id") != job_id:
            raise ValueError("Job 与 FinalResult 不匹配")
        formulas = list(_iter_formula_contexts(final))
        if not formulas:
            raise ValueError("没有可加入知识库的配方")
        for _page, _section, formula in formulas:
            formula_id = str(formula.get("formula_id", ""))
            if confirmed_hashes.get(formula_id) != formula_content_hash(final, formula_id):
                raise ValueError(f"配方 {formula_id} 尚未完成确认或确认已失效")

        final_sha256 = final_result_fingerprint(final)
        connection = self.database._get_conn()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT final_result_sha256, receipt_json FROM knowledge_imports WHERE source_job_id = ?",
                (job_id,),
            ).fetchone()
            if existing:
                if str(existing["final_result_sha256"]) != final_sha256:
                    raise ValueError("该识别记录已加入知识库，但当前结果已经变化")
                receipt = json.loads(str(existing["receipt_json"]))
                connection.rollback()
                return receipt

            confirmed_at = datetime.now(UTC).isoformat()
            formula_ids: list[int] = []
            for page, section, formula in formulas:
                customer = _company_name(page)
                product = str(section.get("product_or_series", {}).get("value", "")).strip()
                customer_id = self._select_or_insert_customer(connection, customer)
                product_id = self._select_or_insert_product(
                    connection, customer_id, product
                )
                formula_ids.append(
                    self._insert_formula(
                        connection,
                        job_id=job_id,
                        page=page,
                        formula=formula,
                        customer_id=customer_id,
                        product_id=product_id,
                        confirmed_at=confirmed_at,
                        formula_hash=confirmed_hashes[str(formula["formula_id"])],
                    )
                )

            receipt = {
                "schema_version": 1,
                "source_job_id": job_id,
                "final_result_sha256": final_sha256,
                "formula_ids": formula_ids,
                "formula_count": len(formula_ids),
                "confirmed_at": confirmed_at,
            }
            connection.execute(
                """
                INSERT INTO knowledge_imports
                    (source_job_id, final_result_sha256, receipt_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    job_id,
                    final_sha256,
                    json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                    confirmed_at,
                ),
            )
            connection.commit()
            return receipt
        except Exception:
            connection.rollback()
            raise

    def timeline(self, customer: str, product: str) -> list[dict[str, Any]]:
        connection = self.database._get_conn()
        rows = connection.execute(
            """
            SELECT f.*, c.name AS customer, p.name AS product
            FROM formulas f
            JOIN customers c ON c.id = f.customer_id
            JOIN products p ON p.id = f.product_id
            WHERE c.name = ? AND p.name = ?
            ORDER BY COALESCE(f.record_date, ''), COALESCE(f.confirmed_at, ''), f.id
            """,
            (customer, product),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.database.close()

    def _select_or_insert_customer(
        self, connection: sqlite3.Connection, name: str
    ) -> int:
        row = connection.execute(
            "SELECT id FROM customers WHERE name = ?", (name,)
        ).fetchone()
        if row:
            return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO customers (name, aliases_json, usage_count) VALUES (?, ?, 1)",
            (name, "[]"),
        )
        return int(cursor.lastrowid)

    def _select_or_insert_product(
        self, connection: sqlite3.Connection, customer_id: int, name: str
    ) -> int:
        row = connection.execute(
            "SELECT id FROM products WHERE customer_id = ? AND name = ? ORDER BY id LIMIT 1",
            (customer_id, name),
        ).fetchone()
        if row:
            return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO products (customer_id, name, aliases_json, usage_count) VALUES (?, ?, ?, 1)",
            (customer_id, name, "[]"),
        )
        return int(cursor.lastrowid)

    def _insert_formula(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        page: dict[str, Any],
        formula: dict[str, Any],
        customer_id: int,
        product_id: int,
        confirmed_at: str,
        formula_hash: str,
    ) -> int:
        formula_no = str(formula.get("formula_no", ""))
        revision = connection.execute(
            """
            SELECT id FROM formulas
            WHERE customer_id = ? AND product_id = ? AND formula_no = ?
            ORDER BY COALESCE(record_date, '') DESC, id DESC LIMIT 1
            """,
            (customer_id, product_id, formula_no),
        ).fetchone()
        cursor = connection.execute(
            """
            INSERT INTO formulas (
                customer_id, product_id, title, fingerprint, formula_no,
                record_date, confirmed_at, source_job_id, source_formula_id,
                source_image_index, revision_of_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                product_id,
                formula_no or "配方",
                formula_hash,
                formula_no,
                str(formula.get("record_date", {}).get("value", "")),
                confirmed_at,
                job_id,
                str(formula["formula_id"]),
                int(page.get("source_image_index", 1)),
                int(revision["id"]) if revision else None,
            ),
        )
        formula_db_id = int(cursor.lastrowid)
        for sequence, material in enumerate(formula.get("materials", []), 1):
            name = str(material.get("name", {}).get("value", ""))
            amount = str(material.get("amount", {}).get("value", ""))
            unit = str(material.get("unit", {}).get("value", ""))
            material_id = self._select_or_insert_material(connection, name, unit)
            connection.execute(
                """
                INSERT INTO formula_items
                    (formula_id, seq, material_id, material_name, amount, normalized_amount, unit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    formula_db_id,
                    sequence,
                    material_id,
                    name,
                    amount,
                    _number_or_none(amount),
                    unit,
                ),
            )
        for sequence, parameter in enumerate(formula.get("process_parameters", []), 1):
            connection.execute(
                """
                INSERT INTO formula_process_parameters (formula_id, seq, name, value, unit)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    formula_db_id,
                    sequence,
                    str(parameter.get("name", {}).get("value", "")),
                    str(parameter.get("value", {}).get("value", "")),
                    str(parameter.get("unit", {}).get("value", "")),
                ),
            )
        return formula_db_id

    def _select_or_insert_material(
        self, connection: sqlite3.Connection, name: str, unit: str
    ) -> int:
        row = connection.execute(
            "SELECT id FROM materials WHERE standard_name = ?", (name,)
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE materials SET usage_count = usage_count + 1 WHERE id = ?",
                (int(row["id"]),),
            )
            return int(row["id"])
        now = datetime.now(UTC).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO materials
                (standard_name, category, default_unit, usage_count, created_at, updated_at)
            VALUES (?, '', ?, 1, ?, ?)
            """,
            (name, unit, now, now),
        )
        return int(cursor.lastrowid)


def _iter_formula_contexts(final: dict[str, Any]):
    for page in final.get("pages", []):
        for section in page.get("product_sections", []):
            for formula in section.get("formulas", []):
                yield page, section, formula


def _company_name(page: dict[str, Any]) -> str:
    company = page.get("company", {})
    return str(company.get("standard_value") or company.get("raw_value") or "").strip()


def _number_or_none(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
