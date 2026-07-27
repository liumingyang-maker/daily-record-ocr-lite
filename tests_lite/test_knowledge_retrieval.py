from datetime import UTC, datetime
from pathlib import Path

from lite_app.knowledge.database import KnowledgeDB
from lite_app.knowledge.retrieval import (
    KnowledgeRetrieval,
    RetrievalRequest,
)


def _seed_term(
    db: KnowledgeDB,
    *,
    value: str,
    customer: str,
    product: str = "",
) -> None:
    now = datetime.now(UTC).isoformat()
    connection = db._get_conn()
    cursor = connection.execute(
        """
        INSERT INTO lexicon_terms (
            term_type, standard_value, normalized_value, source_quality,
            occurrence_count, created_at, updated_at
        ) VALUES ('product', ?, lower(?), 'confirmed', 3, ?, ?)
        """,
        (value, value, now, now),
    )
    connection.execute(
        """
        INSERT INTO lexicon_context_stats (
            term_id, customer_context, product_context, occurrence_count
        ) VALUES (?, ?, ?, 3)
        """,
        (cursor.lastrowid, customer, product),
    )
    connection.commit()


def test_typed_context_ranks_same_customer_product_first(
    tmp_path: Path,
) -> None:
    db = KnowledgeDB(tmp_path / "knowledge.sqlite3")
    db.initialize()
    _seed_term(db, value="G30A", customer="联创")
    _seed_term(db, value="G30B", customer="其他客户")
    db.close()

    retrieval = KnowledgeRetrieval(tmp_path / "knowledge.sqlite3")
    results = retrieval.retrieve(
        RetrievalRequest(
            raw_text="G3OA",
            term_type="product",
            customer="联创",
        )
    )

    assert results[0].value == "G30A"
    assert results[0].context_aligned is True
    assert "customer_context" in results[0].reasons


def test_cross_customer_candidate_is_never_context_aligned(
    tmp_path: Path,
) -> None:
    db = KnowledgeDB(tmp_path / "knowledge.sqlite3")
    db.initialize()
    _seed_term(db, value="G30A", customer="其他客户")
    db.close()

    retrieval = KnowledgeRetrieval(tmp_path / "knowledge.sqlite3")
    result = retrieval.retrieve(
        RetrievalRequest(
            raw_text="G3OA",
            term_type="product",
            customer="联创",
        )
    )[0]

    assert result.value == "G30A"
    assert result.context_aligned is False
    assert "cross_customer_only" in result.reasons


def test_retrieval_is_type_scoped_and_bounded(tmp_path: Path) -> None:
    db = KnowledgeDB(tmp_path / "knowledge.sqlite3")
    db.initialize()
    now = datetime.now(UTC).isoformat()
    connection = db._get_conn()
    for index in range(10):
        connection.execute(
            """
            INSERT INTO lexicon_terms (
                term_type, standard_value, normalized_value,
                source_quality, occurrence_count, created_at, updated_at
            ) VALUES ('material', ?, ?, 'candidate', 1, ?, ?)
            """,
            (f"PA6-{index}", f"pa6-{index}", now, now),
        )
    connection.execute(
        """
        INSERT INTO lexicon_terms (
            term_type, standard_value, normalized_value,
            source_quality, occurrence_count, created_at, updated_at
        ) VALUES ('customer', 'PA6客户', 'pa6客户', 'confirmed', 1, ?, ?)
        """,
        (now, now),
    )
    connection.commit()
    db.close()

    results = KnowledgeRetrieval(
        tmp_path / "knowledge.sqlite3"
    ).retrieve(
        RetrievalRequest(
            raw_text="PA6",
            term_type="material",
            limit=3,
        )
    )

    assert len(results) == 3
    assert all(result.term_type == "material" for result in results)
