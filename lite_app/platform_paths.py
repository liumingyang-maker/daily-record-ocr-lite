"""Resolve replaceable application resources and persistent desktop data."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

APP_DATA_DIR_NAME = "DailyRecordOCR"
DATA_DIR_ENV = "DAILY_RECORD_OCR_DATA_DIR"


def is_frozen() -> bool:
    """Return whether the process is running from a desktop bundle."""
    return bool(getattr(sys, "frozen", False))


def runtime_kind(*, frozen: bool | None = None) -> str:
    """Return the update strategy identifier used by the settings page."""
    return "desktop" if (is_frozen() if frozen is None else frozen) else "source"


def resolve_resource_root() -> Path:
    """Locate bundled read-only resources or the source checkout root."""
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root).resolve()
    return Path(__file__).resolve().parent.parent


def resolve_data_root(
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    frozen: bool | None = None,
    home: Path | None = None,
    resource_root: Path | None = None,
) -> Path:
    """Resolve the only directory allowed to hold replaceable user data."""
    env = os.environ if environment is None else environment
    explicit = str(env.get(DATA_DIR_ENV, "")).strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    frozen_runtime = is_frozen() if frozen is None else frozen
    resources = resolve_resource_root() if resource_root is None else Path(resource_root)
    if not frozen_runtime:
        return (resources / "data").resolve()

    current_platform = sys.platform if platform_name is None else platform_name
    user_home = Path.home() if home is None else Path(home)
    if current_platform == "win32":
        local_app_data = str(env.get("LOCALAPPDATA", "")).strip()
        base = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        return (base / APP_DATA_DIR_NAME).resolve()
    if current_platform == "darwin":
        return (user_home / "Library" / "Application Support" / APP_DATA_DIR_NAME).resolve()

    xdg_data_home = str(env.get("XDG_DATA_HOME", "")).strip()
    base = Path(xdg_data_home) if xdg_data_home else user_home / ".local" / "share"
    return (base / APP_DATA_DIR_NAME).resolve()


def resolve_persistent_path(
    value: str | Path,
    *,
    resource_root: Path | None = None,
    data_root: Path | None = None,
) -> Path:
    """Map a config path under ``data/`` to the persistent desktop root."""
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()

    resources = resolve_resource_root() if resource_root is None else Path(resource_root)
    persistent = resolve_data_root(resource_root=resources) if data_root is None else Path(data_root)
    if candidate.parts and candidate.parts[0].lower() == "data":
        return persistent.joinpath(*candidate.parts[1:]).resolve()
    return (resources / candidate).resolve()


RESOURCE_ROOT = resolve_resource_root()
DATA_ROOT = resolve_data_root(resource_root=RESOURCE_ROOT)
