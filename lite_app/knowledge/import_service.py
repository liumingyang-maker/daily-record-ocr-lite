"""Transactional import of staged personal formulas and recognition lexicon."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..date_values import parse_record_date
from .database import KnowledgeDB
from .import_models import ExtractionIssue, LexiconTermCandidate
from .import_records import DeduplicatedFormula, FormulaSourceRecord


@dataclass(frozen=True)
class StagedIssue:
    source_path: str
    sheet_name: str
    issue: ExtractionIssue


@dataclass(frozen=True)
class PersonalImportBatch:
    run_id: str
    formulas: tuple[DeduplicatedFormula, ...]
    lexicon_terms: tuple[LexiconTermCandidate, ...]
    pending: tuple[StagedIssue, ...] = ()
    exclusions: tuple[StagedIssue, ...] = ()


@dataclass(frozen=True)
class ImportSummary:
    run_id: str
    batch_sha256: str
    formulas_imported: int
    duplicate_formulas: int
    source_count: int
    lexicon_term_count: int
    pending_count: int
    exclusion_count: int
    backup_path: str = ""


class PersonalImportService:
    """Import one validated batch or return its prior idempotent receipt."""

    def __init__(self, db_path: Path) -> None:
        self.database = KnowledgeDB(Path(db_path))
        self.database.initialize()

    def import_batch(self, batch: PersonalImportBatch) -> ImportSummary:
        if not batch.run_id.strip():
            raise ValueError("run_id 不能为空")
        digest = _batch_digest(batch)
        connection = self.database._get_conn()
        existing = connection.execute(
            """
            SELECT batch_sha256, summary_json
            FROM legacy_import_runs WHERE run_id = ?
            """,
            (batch.run_id,),
        ).fetchone()
        if existing:
            if str(existing["batch_sha256"]) != digest:
                raise ValueError("该导入批次已经存在，但批次内容已经变化")
            return ImportSummary(**json.loads(str(existing["summary_json"])))

        backup_path = self._backup_if_active(connection)
        now = datetime.now(UTC).isoformat()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO legacy_import_runs
                    (run_id, batch_sha256, summary_json, created_at)
                VALUES (?, ?, '{}', ?)
                """,
                (batch.run_id, digest, now),
            )
            formulas_imported = 0
            duplicate_formulas = 0
            source_count = 0
            for group in batch.formulas:
                formula_id, inserted = self._upsert_formula_group(
                    connection,
                    batch.run_id,
                    group,
                    now,
                )
                formulas_imported += int(inserted)
                duplicate_formulas += int(not inserted)
                source_count += self._upsert_formula_sources(
                    connection,
                    formula_id,
                    group.sources,
                    now,
                )

            for term in batch.lexicon_terms:
                self._upsert_lexicon_term(connection, term, now)
            for staged in batch.pending:
                self._insert_pending(connection, batch.run_id, staged, now)
            for staged in batch.exclusions:
                self._insert_exclusion(connection, batch.run_id, staged, now)

            summary = ImportSummary(
                run_id=batch.run_id,
                batch_sha256=digest,
                formulas_imported=formulas_imported,
                duplicate_formulas=duplicate_formulas,
                source_count=source_count,
                lexicon_term_count=len(batch.lexicon_terms),
                pending_count=len(batch.pending),
                exclusion_count=len(batch.exclusions),
                backup_path=str(backup_path) if backup_path else "",
            )
            connection.execute(
                """
                UPDATE legacy_import_runs
                SET summary_json = ? WHERE run_id = ?
                """,
                (
                    json.dumps(
                        asdict(summary),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    batch.run_id,
                ),
            )
            connection.commit()
            return summary
        except Exception:
            connection.rollback()
            raise

    def close(self) -> None:
        self.database.close()

    def _backup_if_active(
        self,
        connection: sqlite3.Connection,
    ) -> Path | None:
        if not self.database.db_path.exists():
            return None
        active = connection.execute(
            """
            SELECT EXISTS(SELECT 1 FROM formulas LIMIT 1)
                OR EXISTS(SELECT 1 FROM legacy_import_runs LIMIT 1)
            """
        ).fetchone()[0]
        if not active:
            return None
        backup_dir = self.database.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        target = backup_dir / f"knowledge-before-import-{stamp}.sqlite3"
        backup = sqlite3.connect(target)
        try:
            connection.backup(backup)
        finally:
            backup.close()
        return target

    def _upsert_formula_group(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        group: DeduplicatedFormula,
        now: str,
    ) -> tuple[int, bool]:
        existing = connection.execute(
            """
            SELECT id FROM formulas
            WHERE fingerprint = ? AND source_job_id LIKE 'legacy:%'
            ORDER BY id LIMIT 1
            """,
            (group.fingerprint,),
        ).fetchone()
        if existing:
            return int(existing["id"]), False

        formula = group.formula
        parsed_date = parse_record_date(formula.record_date or "")
        customer_id = _select_or_insert_customer(
            connection,
            formula.customer,
        )
        product_id = _select_or_insert_product(
            connection,
            customer_id,
            formula.product,
        )
        cursor = connection.execute(
            """
            INSERT INTO formulas (
                customer_id, product_id, title, fingerprint, formula_no,
                record_date, record_date_raw, confirmed_at, source_job_id, source_formula_id,
                source_image_index, revision_of_id, source_order, date_status,
                notes_raw, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, NULL)
            """,
            (
                customer_id,
                product_id,
                formula.formula_label or "配方",
                group.fingerprint,
                formula.formula_label or "配方",
                parsed_date.sort_value,
                parsed_date.raw,
                now,
                f"legacy:{run_id}",
                group.fingerprint,
                formula.source_order,
                parsed_date.status,
                formula.notes_raw,
            ),
        )
        formula_id = int(cursor.lastrowid)
        for sequence, item in enumerate(formula.materials, 1):
            material_id = _select_or_insert_material(
                connection,
                item.name_raw,
                now,
            )
            connection.execute(
                """
                INSERT INTO formula_items (
                    formula_id, seq, material_id, material_name,
                    amount, normalized_amount, unit
                ) VALUES (?, ?, ?, ?, ?, ?, '')
                """,
                (
                    formula_id,
                    sequence,
                    material_id,
                    item.name_raw,
                    item.amount_raw,
                    _number_or_none(item.amount_raw),
                ),
            )
        for sequence, parameter in enumerate(
            formula.process_parameters,
            1,
        ):
            connection.execute(
                """
                INSERT INTO formula_process_parameters
                    (formula_id, seq, name, value, unit)
                VALUES (?, ?, ?, ?, '')
                """,
                (
                    formula_id,
                    sequence,
                    parameter.name_raw,
                    parameter.value_raw,
                ),
            )
        return formula_id, True

    def _upsert_formula_sources(
        self,
        connection: sqlite3.Connection,
        formula_id: int,
        sources: tuple[FormulaSourceRecord, ...],
        now: str,
    ) -> int:
        inserted = 0
        for source in sources:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO formula_sources (
                    formula_id, source_path, sheet_name, cell_range, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    formula_id,
                    source.source_path,
                    source.formula.source_span.sheet_name,
                    source.cell_range,
                    now,
                ),
            )
            if not cursor.rowcount:
                row = connection.execute(
                    """
                    SELECT id FROM formula_sources
                    WHERE formula_id = ? AND source_path = ?
                        AND sheet_name = ? AND cell_range = ?
                    """,
                    (
                        formula_id,
                        source.source_path,
                        source.formula.source_span.sheet_name,
                        source.cell_range,
                    ),
                ).fetchone()
                source_id = int(row["id"])
            else:
                source_id = int(cursor.lastrowid)
                inserted += 1
            evidence = (
                ("tight", source.tight_evidence, source.tight_sha256),
                (
                    "context",
                    source.context_evidence,
                    source.context_sha256,
                ),
            )
            for kind, relative_path, sha256 in evidence:
                if relative_path:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO formula_evidence (
                            formula_id, formula_source_id, kind,
                            relative_path, sha256
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            formula_id,
                            source_id,
                            kind,
                            relative_path,
                            sha256,
                        ),
                    )
        return inserted

    def _upsert_lexicon_term(
        self,
        connection: sqlite3.Connection,
        term: LexiconTermCandidate,
        now: str,
    ) -> int:
        normalized = _normalize(term.value)
        if not normalized:
            raise ValueError("词库词条不能为空")
        existing = connection.execute(
            """
            SELECT id, source_quality FROM lexicon_terms
            WHERE term_type = ? AND normalized_value = ?
            """,
            (term.term_type, normalized),
        ).fetchone()
        if existing:
            term_id = int(existing["id"])
            quality = _higher_quality(
                str(existing["source_quality"]),
                term.source_quality,
            )
            connection.execute(
                """
                UPDATE lexicon_terms
                SET occurrence_count = occurrence_count + 1,
                    source_quality = ?, updated_at = ?
                WHERE id = ?
                """,
                (quality, now, term_id),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO lexicon_terms (
                    term_type, standard_value, normalized_value,
                    source_quality, occurrence_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    term.term_type,
                    term.value,
                    normalized,
                    term.source_quality,
                    now,
                    now,
                ),
            )
            term_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO lexicon_context_stats (
                term_id, customer_context, product_context, occurrence_count
            ) VALUES (?, ?, ?, 1)
            ON CONFLICT(term_id, customer_context, product_context)
            DO UPDATE SET occurrence_count = occurrence_count + 1
            """,
            (
                term_id,
                term.customer_context,
                term.product_context,
            ),
        )
        if term.term_type == "material":
            _select_or_insert_material(connection, term.value, now)
        return term_id

    def _insert_pending(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        staged: StagedIssue,
        now: str,
    ) -> None:
        issue = staged.issue
        connection.execute(
            """
            INSERT INTO import_candidates (
                run_id, source_path, sheet_name, start_row, end_row,
                reason, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                staged.source_path,
                staged.sheet_name,
                issue.start_row,
                issue.end_row,
                issue.reason,
                json.dumps(
                    asdict(issue),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
            ),
        )

    def _insert_exclusion(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        staged: StagedIssue,
        now: str,
    ) -> None:
        issue = staged.issue
        connection.execute(
            """
            INSERT INTO import_exclusions (
                run_id, source_path, sheet_name, start_row, end_row,
                reason, details, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                staged.source_path,
                staged.sheet_name,
                issue.start_row,
                issue.end_row,
                issue.reason,
                issue.details,
                now,
            ),
        )


def _batch_digest(batch: PersonalImportBatch) -> str:
    payload = {
        "run_id": batch.run_id,
        "formulas": [asdict(item) for item in batch.formulas],
        "lexicon_terms": [asdict(item) for item in batch.lexicon_terms],
        "pending": [asdict(item) for item in batch.pending],
        "exclusions": [asdict(item) for item in batch.exclusions],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _select_or_insert_customer(
    connection: sqlite3.Connection,
    name: str,
) -> int:
    row = connection.execute(
        "SELECT id FROM customers WHERE name = ?",
        (name,),
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = connection.execute(
        """
        INSERT INTO customers (name, aliases_json, usage_count)
        VALUES (?, '[]', 1)
        """,
        (name,),
    )
    return int(cursor.lastrowid)


def _select_or_insert_product(
    connection: sqlite3.Connection,
    customer_id: int,
    name: str,
) -> int:
    row = connection.execute(
        """
        SELECT id FROM products
        WHERE customer_id = ? AND name = ? ORDER BY id LIMIT 1
        """,
        (customer_id, name),
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = connection.execute(
        """
        INSERT INTO products (customer_id, name, aliases_json, usage_count)
        VALUES (?, ?, '[]', 1)
        """,
        (customer_id, name),
    )
    return int(cursor.lastrowid)


def _select_or_insert_material(
    connection: sqlite3.Connection,
    name: str,
    now: str,
) -> int:
    row = connection.execute(
        "SELECT id FROM materials WHERE standard_name = ?",
        (name,),
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = connection.execute(
        """
        INSERT INTO materials (
            standard_name, category, default_unit, usage_count,
            created_at, updated_at
        ) VALUES (?, 'lexicon', '', 1, ?, ?)
        """,
        (name, now, now),
    )
    return int(cursor.lastrowid)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _higher_quality(left: str, right: str) -> str:
    order = {"reference": 0, "candidate": 1, "confirmed": 2}
    return left if order[left] >= order[right] else right


def _number_or_none(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
