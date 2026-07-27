"""Non-destructive import of an existing source-checkout data directory."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("jobs", "jobs"),
    ("knowledge", "knowledge.sqlite3"),
    ("settings", "settings.json"),
    ("secrets", "secrets.env"),
    ("setup_health", "setup_health.json"),
    ("setup", "setup"),
    ("cache", "cache"),
)
_SOURCE_MARKERS = {relative for _, relative in _CATEGORIES}


class DesktopMigrationError(RuntimeError):
    """Base class for safe desktop migration failures."""


class InvalidMigrationSource(DesktopMigrationError):
    """The selected directory is not a supported project data source."""


class MigrationConfirmationRequired(DesktopMigrationError):
    """The destination contains data and must be backed up explicitly."""


@dataclass(frozen=True)
class MigrationReport:
    source_data_root: Path
    target_data_root: Path
    copied_categories: tuple[str, ...]
    copied_file_counts: dict[str, int]
    backup_path: Path | None

    def to_safe_dict(self) -> dict[str, object]:
        """Return metadata only; never include migrated file contents."""
        return {
            "source_data_root": str(self.source_data_root),
            "target_data_root": str(self.target_data_root),
            "copied_categories": list(self.copied_categories),
            "copied_file_counts": dict(self.copied_file_counts),
            "backup_created": self.backup_path is not None,
            "backup_path": str(self.backup_path) if self.backup_path else None,
        }


def import_legacy_data(
    source: Path,
    target: Path,
    *,
    confirm_non_empty: bool = False,
) -> MigrationReport:
    """Copy supported local data after validating and backing up conflicts."""
    source_data = _resolve_source_data(Path(source))
    target_data = Path(target).expanduser().resolve()
    if source_data == target_data:
        raise InvalidMigrationSource("源数据目录和目标数据目录不能相同")

    backup_path: Path | None = None
    if _directory_has_entries(target_data):
        if not confirm_non_empty:
            raise MigrationConfirmationRequired("目标目录已有数据，需要用户明确确认备份后导入")
        backup_path = _backup_directory(target_data)

    copied_categories: list[str] = []
    copied_file_counts: dict[str, int] = {}
    target_data.mkdir(parents=True, exist_ok=True)
    for category, relative in _CATEGORIES:
        source_path = source_data / relative
        if not source_path.exists():
            continue
        count = _copy_supported_path(source_path, target_data / relative)
        copied_categories.append(category)
        copied_file_counts[category] = count

    return MigrationReport(
        source_data_root=source_data,
        target_data_root=target_data,
        copied_categories=tuple(copied_categories),
        copied_file_counts=copied_file_counts,
        backup_path=backup_path,
    )


def _resolve_source_data(source: Path) -> Path:
    resolved = source.expanduser().resolve()
    candidates = (resolved / "data", resolved)
    for candidate in candidates:
        if candidate.is_dir() and any((candidate / marker).exists() for marker in _SOURCE_MARKERS):
            return candidate.resolve()
    raise InvalidMigrationSource("所选目录不包含可识别的 daily-record-ocr-lite 数据")


def _directory_has_entries(path: Path) -> bool:
    return path.exists() and path.is_dir() and next(path.iterdir(), None) is not None


def _backup_directory(target: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = target.parent / f"{target.name}-backup-{timestamp}"
    backup = base
    suffix = 1
    while backup.exists():
        backup = target.parent / f"{base.name}-{suffix}"
        suffix += 1
    shutil.copytree(target, backup, symlinks=False)
    return backup.resolve()


def _copy_supported_path(source: Path, destination: Path) -> int:
    if source.is_symlink():
        raise InvalidMigrationSource(f"不允许导入符号链接: {source.name}")
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return 1

    count = 0
    for item in source.rglob("*"):
        if item.is_symlink():
            raise InvalidMigrationSource(f"不允许导入符号链接: {item.name}")
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            count += 1
    destination.mkdir(parents=True, exist_ok=True)
    return count
