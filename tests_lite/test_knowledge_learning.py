import sqlite3

import pytest

from lite_app.knowledge.history import KnowledgeHistory
from tests_lite.test_knowledge_history import _confirmed_job


def test_confirmed_formula_teaches_typed_terms_and_context(tmp_path) -> None:
    history = KnowledgeHistory(tmp_path / "knowledge.sqlite3")
    job, final, hashes = _confirmed_job(
        tmp_path,
        "job-learn",
        "2026-07-27",
    )

    history.append_confirmed_job(job, final, hashes)

    connection = sqlite3.connect(tmp_path / "knowledge.sqlite3")
    terms = {
        (row[0], row[1])
        for row in connection.execute(
            "SELECT term_type, standard_value FROM lexicon_terms"
        )
    }
    assert ("customer", "联创") in terms
    assert ("product", "G30A") in terms
    assert ("material", "PA66") in terms
    context = connection.execute(
        """
        SELECT s.customer_context, s.product_context, s.accepted_count
        FROM lexicon_context_stats s
        JOIN lexicon_terms t ON t.id = s.term_id
        WHERE t.term_type = 'material' AND t.standard_value = 'PA66'
        """
    ).fetchone()
    assert context == ("联创", "G30A", 1)
    connection.close()


def test_formula_and_learning_rows_share_one_transaction(
    tmp_path,
    monkeypatch,
) -> None:
    history = KnowledgeHistory(tmp_path / "knowledge.sqlite3")
    job, final, hashes = _confirmed_job(
        tmp_path,
        "job-learning-fail",
        "2026-07-27",
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("controlled learning failure")

    monkeypatch.setattr(history, "_learn_formula_terms", fail)
    with pytest.raises(RuntimeError, match="controlled learning"):
        history.append_confirmed_job(job, final, hashes)

    connection = sqlite3.connect(tmp_path / "knowledge.sqlite3")
    assert connection.execute(
        "SELECT COUNT(*) FROM formulas"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM lexicon_terms"
    ).fetchone()[0] == 0
    connection.close()
