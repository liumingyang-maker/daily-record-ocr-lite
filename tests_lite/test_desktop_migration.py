from pathlib import Path

import pytest


def _source_checkout(root: Path) -> Path:
    data = root / "data"
    (data / "jobs" / "job-1").mkdir(parents=True)
    (data / "jobs" / "job-1" / "job.json").write_text('{"status":"READY"}', encoding="utf-8")
    (data / "settings.json").write_text('{"demo_mode":false}', encoding="utf-8")
    (data / "secrets.env").write_text("VISION_API_KEY=test-only-secret", encoding="utf-8")
    (data / "knowledge.sqlite3").write_bytes(b"sqlite-placeholder")
    return root


def test_import_copies_supported_data_without_modifying_source(tmp_path: Path):
    from lite_app.desktop_migration import import_legacy_data

    source = _source_checkout(tmp_path / "old-checkout")
    target = tmp_path / "desktop-data"
    before = (source / "data" / "jobs" / "job-1" / "job.json").read_bytes()

    report = import_legacy_data(source, target)

    assert (target / "jobs" / "job-1" / "job.json").read_bytes() == before
    assert (source / "data" / "jobs" / "job-1" / "job.json").read_bytes() == before
    assert report.copied_categories == ("jobs", "knowledge", "settings", "secrets")
    assert report.backup_path is None
    assert "test-only-secret" not in report.to_safe_dict().__repr__()


def test_import_accepts_data_directory_itself(tmp_path: Path):
    from lite_app.desktop_migration import import_legacy_data

    source = _source_checkout(tmp_path / "old-checkout") / "data"
    target = tmp_path / "desktop-data"

    report = import_legacy_data(source, target)

    assert report.source_data_root == source.resolve()
    assert (target / "settings.json").exists()


def test_non_empty_target_requires_explicit_confirmation(tmp_path: Path):
    from lite_app.desktop_migration import MigrationConfirmationRequired, import_legacy_data

    source = _source_checkout(tmp_path / "old-checkout")
    target = tmp_path / "desktop-data"
    target.mkdir()
    (target / "settings.json").write_text("existing", encoding="utf-8")

    with pytest.raises(MigrationConfirmationRequired):
        import_legacy_data(source, target)

    assert (target / "settings.json").read_text(encoding="utf-8") == "existing"


def test_confirmed_import_backs_up_target_before_copy(tmp_path: Path):
    from lite_app.desktop_migration import import_legacy_data

    source = _source_checkout(tmp_path / "old-checkout")
    target = tmp_path / "desktop-data"
    target.mkdir()
    (target / "settings.json").write_text("existing", encoding="utf-8")

    report = import_legacy_data(source, target, confirm_non_empty=True)

    assert report.backup_path is not None
    assert (report.backup_path / "settings.json").read_text(encoding="utf-8") == "existing"
    assert (target / "settings.json").read_text(encoding="utf-8") == '{"demo_mode":false}'


def test_invalid_source_is_rejected_without_creating_target(tmp_path: Path):
    from lite_app.desktop_migration import InvalidMigrationSource, import_legacy_data

    source = tmp_path / "not-this-project"
    source.mkdir()
    (source / "notes.txt").write_text("unrelated", encoding="utf-8")
    target = tmp_path / "desktop-data"

    with pytest.raises(InvalidMigrationSource):
        import_legacy_data(source, target)

    assert not target.exists()


def test_import_rejects_same_source_and_target(tmp_path: Path):
    from lite_app.desktop_migration import InvalidMigrationSource, import_legacy_data

    source = _source_checkout(tmp_path / "old-checkout") / "data"

    with pytest.raises(InvalidMigrationSource):
        import_legacy_data(source, source)
