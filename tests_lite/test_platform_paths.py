from pathlib import Path


def test_explicit_data_directory_has_highest_priority(tmp_path: Path):
    from lite_app.platform_paths import resolve_data_root

    explicit = tmp_path / "chosen-data"
    result = resolve_data_root(
        environment={"DAILY_RECORD_OCR_DATA_DIR": str(explicit)},
        platform_name="win32",
        frozen=True,
        home=tmp_path / "home",
    )

    assert result == explicit.resolve()


def test_windows_frozen_data_uses_local_app_data(tmp_path: Path):
    from lite_app.platform_paths import resolve_data_root

    result = resolve_data_root(
        environment={"LOCALAPPDATA": str(tmp_path / "Local")},
        platform_name="win32",
        frozen=True,
        home=tmp_path / "home",
    )

    assert result == (tmp_path / "Local" / "DailyRecordOCR").resolve()


def test_macos_frozen_data_uses_application_support(tmp_path: Path):
    from lite_app.platform_paths import resolve_data_root

    result = resolve_data_root(
        environment={},
        platform_name="darwin",
        frozen=True,
        home=tmp_path / "home",
    )

    assert result == (
        tmp_path / "home" / "Library" / "Application Support" / "DailyRecordOCR"
    ).resolve()


def test_source_checkout_keeps_project_data_directory(tmp_path: Path):
    from lite_app.platform_paths import resolve_data_root

    result = resolve_data_root(
        environment={},
        platform_name="win32",
        frozen=False,
        home=tmp_path / "home",
        resource_root=tmp_path / "checkout",
    )

    assert result == (tmp_path / "checkout" / "data").resolve()


def test_data_path_rehomes_only_project_data_paths(tmp_path: Path):
    from lite_app.platform_paths import resolve_persistent_path

    resource_root = tmp_path / "app"
    data_root = tmp_path / "persistent"

    assert resolve_persistent_path(
        "data/jobs", resource_root=resource_root, data_root=data_root
    ) == (data_root / "jobs").resolve()
    assert resolve_persistent_path(
        "config/export.yaml", resource_root=resource_root, data_root=data_root
    ) == (resource_root / "config" / "export.yaml").resolve()


def test_runtime_kind_distinguishes_source_and_desktop():
    from lite_app.platform_paths import runtime_kind

    assert runtime_kind(frozen=False) == "source"
    assert runtime_kind(frozen=True) == "desktop"
