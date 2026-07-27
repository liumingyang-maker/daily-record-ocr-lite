"""Single runtime resolver for the active knowledge database."""

from __future__ import annotations

import os
from pathlib import Path

from ..config import DATA_ROOT


def resolve_knowledge_db_path() -> Path:
    """Resolve the private override or the active data-root database."""
    configured = os.environ.get("KNOWLEDGE_DB_PATH")
    return Path(configured or DATA_ROOT / "knowledge.sqlite3").expanduser().resolve()
