"""Destructive cache administration must stay inside the exact cache root."""

import pytest

from scripts import cache_admin


@pytest.mark.parametrize("relative", ["data", "data/jobs", "data/secrets.env"])
def test_cache_clear_rejects_non_cache_targets(tmp_path, monkeypatch, relative, capsys):
    monkeypatch.setattr(cache_admin, "ROOT", tmp_path)
    target = tmp_path / relative
    if target.suffix:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("keep", encoding="utf-8")
    else:
        target.mkdir(parents=True, exist_ok=True)
        (target / "keep.txt").write_text("keep", encoding="utf-8")

    assert cache_admin.main(["clear", "--yes", "--root", str(target)]) == 2
    assert target.exists()
    assert "data/cache" in capsys.readouterr().out


def test_cache_clear_only_recreates_expected_namespaces(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_admin, "ROOT", tmp_path)
    cache_root = tmp_path / "data" / "cache"
    (cache_root / "ocr").mkdir(parents=True)
    (cache_root / "ocr" / "entry.json").write_text("{}", encoding="utf-8")

    assert cache_admin.main(["clear", "--yes", "--root", str(cache_root)]) == 0
    assert sorted(path.name for path in cache_root.iterdir()) == ["ocr", "vision"]
    assert list(cache_root.rglob("*.json")) == []
