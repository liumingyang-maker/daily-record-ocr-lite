"""Transactional, append-only customer/product formula history."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
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
                formula_db_id = self._insert_formula(
                    connection,
                    job_id=job_id,
                    page=page,
                    formula=formula,
                    customer_id=customer_id,
                    product_id=product_id,
                    confirmed_at=confirmed_at,
                    formula_hash=confirmed_hashes[str(formula["formula_id"])],
                )
                formula_ids.append(formula_db_id)
                self._learn_formula_terms(
                    connection,
                    customer=customer,
                    product=product,
                    formula=formula,
                    confirmed_at=confirmed_at,
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

    def tree(self, query: str = "") -> dict[str, Any]:
        connection = self.database._get_conn()
        pattern = f"%{query.strip()}%"
        rows = connection.execute(
            """
            SELECT f.id, f.formula_no, f.record_date, f.date_status,
                   f.confirmed_at,
                   c.id AS customer_id, c.name AS customer,
                   p.id AS product_id, p.name AS product
            FROM formulas f
            LEFT JOIN customers c ON c.id = f.customer_id
            LEFT JOIN products p ON p.id = f.product_id
            WHERE ? = '%%' OR COALESCE(c.name, '') LIKE ?
                OR COALESCE(p.name, '') LIKE ? OR COALESCE(f.record_date, '') LIKE ?
            ORDER BY COALESCE(c.name, ''), COALESCE(p.name, ''),
                     COALESCE(f.record_date, ''), COALESCE(f.confirmed_at, ''), f.id
            """,
            (pattern, pattern, pattern, pattern),
        ).fetchall()
        customers: dict[tuple[int | None, str], dict[str, Any]] = {}
        products: dict[tuple[tuple[int | None, str], int | None, str], dict[str, Any]] = {}
        for row in rows:
            customer_key = (row["customer_id"], str(row["customer"] or "未记录客户"))
            customer = customers.setdefault(
                customer_key,
                {
                    "id": row["customer_id"],
                    "name": customer_key[1],
                    "products": [],
                },
            )
            product_key = (
                customer_key,
                row["product_id"],
                str(row["product"] or "未记录产品"),
            )
            product = products.get(product_key)
            if product is None:
                product = {
                    "id": row["product_id"],
                    "name": product_key[2],
                    "formula_count": 0,
                    "formulas": [],
                }
                products[product_key] = product
                customer["products"].append(product)
            product["formulas"].append(
                {
                    "id": int(row["id"]),
                    "formula_no": str(row["formula_no"] or "配方"),
                    "record_date": str(row["record_date"] or ""),
                    "date_status": str(row["date_status"] or "UNKNOWN"),
                    "confirmed_at": str(row["confirmed_at"] or ""),
                }
            )
            product["formula_count"] += 1
        return {"customers": list(customers.values()), "query": query}

    def formula_detail(self, formula_id: int) -> dict[str, Any]:
        connection = self.database._get_conn()
        row = connection.execute(
            """
            SELECT f.*, c.name AS customer, p.name AS product
            FROM formulas f
            LEFT JOIN customers c ON c.id = f.customer_id
            LEFT JOIN products p ON p.id = f.product_id
            WHERE f.id = ?
            """,
            (formula_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"历史配方不存在: {formula_id}")
        materials = connection.execute(
            """
            SELECT seq, material_name AS name, amount, unit
            FROM formula_items WHERE formula_id = ? ORDER BY seq, id
            """,
            (formula_id,),
        ).fetchall()
        process = connection.execute(
            """
            SELECT seq, name, value, unit
            FROM formula_process_parameters WHERE formula_id = ? ORDER BY seq, id
            """,
            (formula_id,),
        ).fetchall()
        evidence = connection.execute(
            """
            SELECT e.id, e.kind, e.relative_path, e.sha256,
                   s.source_path, s.sheet_name, s.cell_range
            FROM formula_evidence e
            JOIN formula_sources s ON s.id = e.formula_source_id
            WHERE e.formula_id = ?
            ORDER BY s.id, CASE e.kind WHEN 'tight' THEN 0 ELSE 1 END
            """,
            (formula_id,),
        ).fetchall()
        return {
            "id": int(row["id"]),
            "customer": str(row["customer"] or "未记录客户"),
            "product": str(row["product"] or "未记录产品"),
            "formula_no": str(row["formula_no"] or row["title"] or "配方"),
            "record_date": str(row["record_date"] or ""),
            "date_status": str(row["date_status"] or "UNKNOWN"),
            "notes_raw": str(row["notes_raw"] or ""),
            "confirmed_at": str(row["confirmed_at"] or ""),
            "source_job_id": str(row["source_job_id"] or ""),
            "source_formula_id": str(row["source_formula_id"] or ""),
            "source_image_index": int(row["source_image_index"] or 0),
            "revision_of_id": row["revision_of_id"],
            "materials": [dict(item) for item in materials],
            "process": [dict(item) for item in process],
            "evidence": [dict(item) for item in evidence],
        }

    def pending_review(self, limit: int = 100) -> dict[str, Any]:
        connection = self.database._get_conn()
        rows = connection.execute(
            """
            SELECT id, source_path, sheet_name, start_row, end_row,
                   reason, payload_json
            FROM import_candidates
            WHERE status = 'PENDING_REVIEW'
            ORDER BY id
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
        total = connection.execute(
            """
            SELECT COUNT(*) FROM import_candidates
            WHERE status = 'PENDING_REVIEW'
            """
        ).fetchone()[0]
        items = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                payload = {}
            formula = payload.get("formula") or {}
            items.append(
                {
                    "id": int(row["id"]),
                    "reason": str(row["reason"]),
                    "source_path": str(row["source_path"]),
                    "sheet_name": str(row["sheet_name"]),
                    "rows": [int(row["start_row"]), int(row["end_row"])],
                    "customer": str(formula.get("customer", "")),
                    "product": str(formula.get("product", "")),
                    "formula_label": str(
                        formula.get("formula_label", "")
                    ),
                    "materials": [
                        str(material.get("name_raw", ""))
                        for material in formula.get("materials", [])
                        if str(material.get("name_raw", "")).strip()
                    ],
                }
            )
        return {"total": int(total), "items": items}

    def compare(self, left_id: int, right_id: int) -> dict[str, Any]:
        left = self.formula_detail(left_id)
        right = self.formula_detail(right_id)
        return {
            "left": left,
            "right": right,
            "materials": _compare_named_rows(left["materials"], right["materials"], "amount"),
            "process": _compare_named_rows(left["process"], right["process"], "value"),
        }

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

    def _learn_formula_terms(
        self,
        connection: sqlite3.Connection,
        *,
        customer: str,
        product: str,
        formula: dict[str, Any],
        confirmed_at: str,
    ) -> None:
        terms: list[tuple[str, str]] = [
            ("customer", customer),
            ("product", product),
        ]
        terms.extend(
            (
                "material",
                str(material.get("name", {}).get("value", "")),
            )
            for material in formula.get("materials", [])
        )
        terms.extend(
            (
                "process",
                str(parameter.get("name", {}).get("value", "")),
            )
            for parameter in formula.get("process_parameters", [])
        )
        notes = str(formula.get("notes", {}).get("value", "")).strip()
        if notes:
            terms.append(("note_phrase", notes))
        for term_type, value in terms:
            value = value.strip()
            normalized = _normalize_lexicon(value)
            if not normalized:
                continue
            connection.execute(
                """
                INSERT INTO lexicon_terms (
                    term_type, standard_value, normalized_value,
                    source_quality, occurrence_count, accepted_count,
                    rejected_count, created_at, updated_at
                ) VALUES (?, ?, ?, 'confirmed', 1, 1, 0, ?, ?)
                ON CONFLICT(term_type, normalized_value) DO UPDATE SET
                    standard_value = excluded.standard_value,
                    source_quality = 'confirmed',
                    occurrence_count = occurrence_count + 1,
                    accepted_count = accepted_count + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    term_type,
                    value,
                    normalized,
                    confirmed_at,
                    confirmed_at,
                ),
            )
            term_id = connection.execute(
                """
                SELECT id FROM lexicon_terms
                WHERE term_type = ? AND normalized_value = ?
                """,
                (term_type, normalized),
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO lexicon_context_stats (
                    term_id, customer_context, product_context,
                    occurrence_count, accepted_count, rejected_count
                ) VALUES (?, ?, ?, 1, 1, 0)
                ON CONFLICT(
                    term_id, customer_context, product_context
                ) DO UPDATE SET
                    occurrence_count = occurrence_count + 1,
                    accepted_count = accepted_count + 1
                """,
                (term_id, customer, product),
            )

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
                source_image_index, revision_of_id, date_status, notes_raw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                (
                    "KNOWN"
                    if str(
                        formula.get("record_date", {}).get("value", "")
                    ).strip()
                    else "UNKNOWN"
                ),
                str(formula.get("notes", {}).get("value", "")),
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


def _normalize_lexicon(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


def _compare_named_rows(
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    value_key: str,
) -> dict[str, dict[str, str]]:
    before = {str(row["name"]): row for row in before_rows}
    after = {str(row["name"]): row for row in after_rows}
    return {
        name: {
            "before": str(before.get(name, {}).get(value_key, "")),
            "after": str(after.get(name, {}).get(value_key, "")),
            "unit_before": str(before.get(name, {}).get("unit", "")),
            "unit_after": str(after.get(name, {}).get("unit", "")),
        }
        for name in sorted(set(before) | set(after))
    }
