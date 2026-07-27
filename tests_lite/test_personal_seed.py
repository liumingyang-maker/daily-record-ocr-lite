import hashlib
import json
from pathlib import Path

import pytest

from lite_app.personal_seed import (
    PersonalSeedError,
    initialize_personal_seed,
)


def _seed(root: Path) -> None:
    files = {
        "knowledge.sqlite3": b"seed-database",
        "personal_imports/v1/evidence/a.png": b"evidence",
        "secrets.env": b"VISION_API_KEY=private-build-value\n",
        "settings.json": b'{"vision":{"model":"qwen3.7-plus"}}\n',
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {
        "schema_version": "personal-seed-v1",
        "version": "v1.1.0-personal.1",
        "files": [
            {
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
            for name, content in sorted(files.items())
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def test_first_install_copies_seed_database_evidence_and_private_config(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed"
    data = tmp_path / "data"
    _seed(seed)

    result = initialize_personal_seed(
        seed,
        data,
        "v1.1.0-personal.1",
    )

    assert result.status == "INITIALIZED"
    assert (data / "knowledge.sqlite3").read_bytes() == b"seed-database"
    assert (
        data / "personal_imports/v1/evidence/a.png"
    ).read_bytes() == b"evidence"
    assert (data / "secrets.env").exists()
    assert (data / "settings.json").exists()


def test_upgrade_preserves_learned_database_and_user_key(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    data = tmp_path / "data"
    _seed(seed)
    initialize_personal_seed(seed, data, "v1.1.0-personal.1")
    (data / "knowledge.sqlite3").write_bytes(b"learned-user-data")
    (data / "secrets.env").write_bytes(b"VISION_API_KEY=user-override\n")
    (data / "settings.json").write_bytes(b'{"vision":{"timeout":300}}\n')
    protected = {
        name: hashlib.sha256((data / name).read_bytes()).hexdigest()
        for name in ("knowledge.sqlite3", "secrets.env", "settings.json")
    }

    result = initialize_personal_seed(
        seed,
        data,
        "v1.1.1-personal.1",
    )

    assert result.status == "PRESERVED"
    assert (data / "knowledge.sqlite3").read_bytes() == b"learned-user-data"
    assert (data / "secrets.env").read_bytes() == (
        b"VISION_API_KEY=user-override\n"
    )
    assert {
        name: hashlib.sha256((data / name).read_bytes()).hexdigest()
        for name in ("knowledge.sqlite3", "secrets.env", "settings.json")
    } == protected


def test_seed_checksum_mismatch_fails_before_writing_data(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed"
    data = tmp_path / "data"
    _seed(seed)
    (seed / "knowledge.sqlite3").write_bytes(b"seed-databasE")

    with pytest.raises(PersonalSeedError, match="checksum"):
        initialize_personal_seed(seed, data, "v1.1.0-personal.1")

    assert not data.exists()
