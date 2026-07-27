from __future__ import annotations

from pathlib import Path

from lite_app.grouping.review import GroupingReviewService
from lite_app.knowledge import path as knowledge_path_module
from lite_app.knowledge.path import resolve_knowledge_db_path


def test_resolver_uses_private_database_override(monkeypatch, tmp_path: Path) -> None:
    expected = tmp_path / "private.sqlite3"
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(expected))

    assert resolve_knowledge_db_path() == expected.resolve()


def test_resolver_defaults_to_active_data_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KNOWLEDGE_DB_PATH", raising=False)
    monkeypatch.setattr(knowledge_path_module, "DATA_ROOT", tmp_path)

    assert resolve_knowledge_db_path() == (tmp_path / "knowledge.sqlite3").resolve()


def test_grouping_review_uses_same_private_database_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    expected = tmp_path / "private.sqlite3"
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(expected))

    service = GroupingReviewService(tmp_path / "job", "job")

    assert service.knowledge_db_path == expected.resolve()
