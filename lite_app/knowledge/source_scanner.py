"""Read-only classification for mixed legacy knowledge sources."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SourceAction = Literal["candidate", "exclude", "review"]

SUPPORTED_WORKBOOK_SUFFIXES = {".xlsx", ".xls"}
EXCLUDED_DIRECTORY_NAMES = {
    "1报告合集",
    "2各种表格",
    "成份表",
}
EXCLUDED_NAME_TOKENS = {
    "sgs",
    "价格",
    "价目",
    "合同",
    "发票",
    "对账",
    "成份",
    "成分",
    "报价",
    "报告",
    "标签",
    "检验",
    "检测",
    "物性",
    "跟踪表",
}


@dataclass(frozen=True)
class SourceDecision:
    """One deterministic classification result relative to a scan root."""

    path: Path
    action: SourceAction
    reason: str
    customer_hint: str = ""


def classify_source(relative_path: Path) -> SourceDecision:
    """Classify a relative source path without reading or mutating it."""
    path = Path(relative_path)
    parts = path.parts
    name = path.name
    normalized = path.as_posix().casefold()

    if "__MACOSX" in parts or name.startswith("._") or name == ".DS_Store":
        return SourceDecision(path, "exclude", "MACOS_METADATA")
    if name.startswith("~$"):
        return SourceDecision(path, "exclude", "TEMPORARY_FILE")
    if path.suffix.casefold() not in SUPPORTED_WORKBOOK_SUFFIXES:
        return SourceDecision(path, "exclude", "UNSUPPORTED_FORMAT")
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in parts[:-1]):
        return SourceDecision(path, "exclude", "NON_FORMULA_DOCUMENT")
    if any(token in normalized for token in EXCLUDED_NAME_TOKENS):
        return SourceDecision(path, "exclude", "NON_FORMULA_DOCUMENT")

    customer_hint = parts[0] if len(parts) > 1 else ""
    return SourceDecision(
        path=path,
        action="candidate",
        reason="FORMULA_WORKBOOK",
        customer_hint=customer_hint,
    )


def scan_sources(root: Path) -> list[SourceDecision]:
    """Scan regular files below *root* without following directory links."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    relative_files: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if not (current_path / name).is_symlink()
        ]
        for name in files:
            absolute = current_path / name
            if absolute.is_symlink():
                continue
            relative_files.append(absolute.relative_to(root))

    return [
        classify_source(path)
        for path in sorted(relative_files, key=lambda item: item.as_posix().casefold())
    ]
