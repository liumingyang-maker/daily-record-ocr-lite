import sqlite3
from pathlib import Path

import pytest

from lite_app.knowledge.import_models import (
    ExtractionIssue,
    FormulaCandidate,
    LexiconTermCandidate,
    MaterialCandidate,
    ProcessParameterCandidate,
    SourceSpan,
)
from lite_app.knowledge.import_records import (
    FormulaSourceRecord,
    deduplicate_formulas,
)
from lite_app.knowledge.import_service import (
    PersonalImportBatch,
    PersonalImportService,
    StagedIssue,
)


def _formula() -> FormulaCandidate:
    return FormulaCandidate(
        customer="联创",
        product="G30A",
        record_date=None,
        date_status="UNKNOWN",
        source_order=2,
        formula_label="配方2",
        materials=(
            MaterialCandidate("PA6", "55", 2),
            MaterialCandidate("玻纤", "35-36", 3),
        ),
        process_parameters=(ProcessParameterCandidate("主机", "300", 2),),
        notes_raw="客户要求保持黑度",
        confidence=0.95,
        source_span=SourceSpan("G30A", 7, 11, 1, 3),
    )


def _batch(run_id: str = "legacy-run-1") -> PersonalImportBatch:
    formula = _formula()
    groups = deduplicate_formulas(
        [
            FormulaSourceRecord(
                formula,
                "联创/联创.xlsx",
                "G30A!A7:C11",
                "evidence/a_tight.png",
                "evidence/a_context.png",
            ),
            FormulaSourceRecord(
                formula,
                "联创/备份.xlsx",
                "G30A!A7:C11",
                "evidence/b_tight.png",
                "evidence/b_context.png",
            ),
        ]
    )
    return PersonalImportBatch(
        run_id=run_id,
        formulas=groups,
        lexicon_terms=(
            LexiconTermCandidate(
                "customer",
                "联创",
                "candidate",
                customer_context="联创",
                product_context="G30A",
            ),
            LexiconTermCandidate(
                "product",
                "G30A",
                "candidate",
                customer_context="联创",
                product_context="G30A",
            ),
            LexiconTermCandidate(
                "material",
                "PA6",
                "candidate",
                customer_context="联创",
                product_context="G30A",
            ),
            LexiconTermCandidate(
                "material",
                "玻纤",
                "reference",
                customer_context="联创",
                product_context="G30A",
            ),
        ),
        pending=(
            StagedIssue(
                "联创/冲突.xlsx",
                "Sheet1",
                ExtractionIssue("PRODUCT_CONFLICT", 2, 4, "需要确认"),
            ),
        ),
        exclusions=(
            StagedIssue(
                "联创/模板.xlsx",
                "Sheet1",
                ExtractionIssue("EMPTY_TEMPLATE", 7, 10),
            ),
        ),
    )


def _count(db_path: Path, table: str) -> int:
    connection = sqlite3.connect(db_path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def test_imports_formulas_lexicon_sources_pending_and_exclusions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    service = PersonalImportService(db_path)

    summary = service.import_batch(_batch())

    assert summary.formulas_imported == 1
    assert summary.duplicate_formulas == 0
    assert summary.pending_count == 1
    assert summary.exclusion_count == 1
    assert _count(db_path, "formulas") == 1
    assert _count(db_path, "formula_items") == 2
    assert _count(db_path, "formula_process_parameters") == 1
    assert _count(db_path, "formula_sources") == 2
    assert _count(db_path, "formula_evidence") == 4
    assert _count(db_path, "lexicon_terms") == 4
    assert _count(db_path, "import_candidates") == 1
    assert _count(db_path, "import_exclusions") == 1

    connection = sqlite3.connect(db_path)
    row = connection.execute(
        "SELECT record_date, date_status, source_order, notes_raw FROM formulas"
    ).fetchone()
    connection.close()
    assert row == (None, "UNKNOWN", 2, "客户要求保持黑度")


def test_same_import_run_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    service = PersonalImportService(db_path)

    first = service.import_batch(_batch())
    second = service.import_batch(_batch())

    assert second == first
    assert _count(db_path, "formulas") == 1
    assert _count(db_path, "formula_sources") == 2
    assert _count(db_path, "legacy_import_runs") == 1


def test_same_run_id_rejects_changed_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    service = PersonalImportService(db_path)
    service.import_batch(_batch())
    changed = _batch()
    changed = PersonalImportBatch(
        run_id=changed.run_id,
        formulas=changed.formulas,
        lexicon_terms=changed.lexicon_terms[:-1],
        pending=changed.pending,
        exclusions=changed.exclusions,
    )

    with pytest.raises(ValueError, match="内容已经变化"):
        service.import_batch(changed)


def test_failure_rolls_back_the_entire_batch(tmp_path: Path) -> None:
    class FailingService(PersonalImportService):
        def _upsert_lexicon_term(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("forced lexicon failure")

    db_path = tmp_path / "knowledge.sqlite3"
    service = FailingService(db_path)

    with pytest.raises(RuntimeError, match="forced lexicon failure"):
        service.import_batch(_batch())

    assert _count(db_path, "formulas") == 0
    assert _count(db_path, "legacy_import_runs") == 0
