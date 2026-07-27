"""Stable-release awareness for source and desktop installations."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from typing import Any

import httpx

from .platform_paths import runtime_kind

RELEASES_API = "https://api.github.com/repos/liumingyang-maker/daily-record-ocr-lite/releases"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def select_latest_stable(releases: list[dict[str, Any]]) -> dict[str, str] | None:
    """Select the newest published non-prerelease semantic version."""
    candidates: list[tuple[tuple[int, int, int], dict[str, str]]] = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name", "")).strip()
        version = _version_tuple(tag)
        url = str(release.get("html_url", "")).strip()
        if version is None or not url.startswith(
            "https://github.com/liumingyang-maker/daily-record-ocr-lite/releases/"
        ):
            continue
        candidates.append(
            (version, {"version": ".".join(str(part) for part in version), "tag": tag, "url": url})
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def build_update_result(
    current_version: str,
    latest: dict[str, str] | None,
    *,
    install_kind: str | None = None,
) -> dict[str, object]:
    kind = runtime_kind() if install_kind is None else install_kind
    current = _version_tuple(current_version)
    newest = _version_tuple(latest["version"]) if latest else None
    available = bool(current and newest and newest > current)
    return {
        "status": "OK",
        "current_version": current_version,
        "latest_version": latest["version"] if latest else None,
        "latest_tag": latest["tag"] if latest else None,
        "release_url": latest["url"] if latest else None,
        "update_available": available,
        "install_kind": kind,
        "update_method": "installer" if kind == "desktop" else "git",
        "instructions": update_instructions(kind),
    }


def check_for_stable_update(
    current_version: str,
    *,
    fetcher: Callable[[], list[dict[str, Any]]] | None = None,
    install_kind: str | None = None,
) -> dict[str, object]:
    """Check GitHub without returning transport or credential details."""
    try:
        releases = (fetcher or _fetch_releases)()
        return build_update_result(
            current_version,
            select_latest_stable(releases),
            install_kind=install_kind,
        )
    except Exception:
        return {
            "status": "UNAVAILABLE",
            "current_version": current_version,
            "error_category": "UPDATE_CHECK_FAILED",
            "update_available": False,
            "install_kind": install_kind or runtime_kind(),
        }


def update_instructions(install_kind: str, *, platform_name: str | None = None) -> str:
    if install_kind != "desktop":
        return "源码安装版请按 README 的稳定 Tag 步骤使用 Git 更新。"
    platform_value = sys.platform if platform_name is None else platform_name
    if platform_value == "darwin":
        return "下载最新稳定版 DMG，把新应用拖入“应用程序”并覆盖旧版本；用户数据会保留。"
    return "下载最新稳定版 Windows 安装包并覆盖安装；用户数据会保留。"


def _fetch_releases() -> list[dict[str, Any]]:
    response = httpx.get(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json"},
        follow_redirects=False,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("GitHub releases response must be a list")
    return [item for item in payload if isinstance(item, dict)]
