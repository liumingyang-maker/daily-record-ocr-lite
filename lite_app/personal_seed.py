"""First-install personal data seeding with upgrade preservation."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class PersonalSeedError(ValueError):
    pass


@dataclass(frozen=True)
class PersonalSeedResult:
    status: str
    version: str
    file_count: int


def initialize_personal_seed(
    seed_dir: Path,
    data_dir: Path,
    version: str,
) -> PersonalSeedResult:
    """Install a verified seed once; never replace an active personal DB."""
    seed = Path(seed_dir).resolve()
    data = Path(data_dir).resolve()
    manifest = _validate_seed(seed)
    files = manifest["files"]
    active_database = data / "knowledge.sqlite3"
    if active_database.exists():
        return PersonalSeedResult(
            status="PRESERVED",
            version=version,
            file_count=0,
        )

    data.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in files:
        relative = PurePosixPath(item["path"])
        source = seed.joinpath(*relative.parts)
        destination = data.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(
            destination.suffix + ".personal-seed.tmp"
        )
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
        copied += 1
    marker = {
        "schema_version": "personal-seed-state-v1",
        "seed_version": str(manifest["version"]),
        "installed_version": version,
        "file_count": copied,
    }
    (data / "personal-seed-state.json").write_text(
        json.dumps(marker, sort_keys=True),
        encoding="utf-8",
    )
    return PersonalSeedResult(
        status="INITIALIZED",
        version=version,
        file_count=copied,
    )


def _validate_seed(seed: Path) -> dict[str, Any]:
    manifest_path = seed / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersonalSeedError("invalid personal seed manifest") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "personal-seed-v1"
        or not isinstance(manifest.get("files"), list)
    ):
        raise PersonalSeedError("unsupported personal seed manifest")
    seen: set[str] = set()
    has_database = False
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise PersonalSeedError("invalid personal seed file entry")
        name = str(item.get("path", ""))
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or "\\" in name
            or any(part in {"", ".", ".."} for part in path.parts)
            or name in seen
        ):
            raise PersonalSeedError("unsafe personal seed path")
        seen.add(name)
        has_database = has_database or name == "knowledge.sqlite3"
        source = seed.joinpath(*path.parts)
        if not source.is_file():
            raise PersonalSeedError(f"missing personal seed file: {name}")
        size = source.stat().st_size
        if size != item.get("size"):
            raise PersonalSeedError(f"size mismatch for {name}")
        if _sha256(source) != item.get("sha256"):
            raise PersonalSeedError(f"checksum mismatch for {name}")
    if not has_database:
        raise PersonalSeedError("personal seed database is missing")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
