import hashlib
import json
import sqlite3
import stat
import zipfile
from pathlib import Path
from typing import Callable

import pytest

from lite_app.knowledge.package import (
    KnowledgePackageError,
    KnowledgePackageService,
    validate_knowledge_package,
)


def _jsonl(record: dict[str, object]) -> bytes:
    return (json.dumps(record, ensure_ascii=False) + "\n").encode()


def _valid_members() -> dict[str, bytes]:
    return {
        "formulas.jsonl": _jsonl(
            {
                "record_type": "FORMULA",
                "formula_id": "formula-1",
                "customer": "联创",
                "product": "G30A",
                "record_date": "2024-07-12",
                "date_status": "KNOWN",
                "formula_label": "配方1",
                "materials": [
                    {"name_raw": "PA6", "amount_raw": "55"},
                    {"name_raw": "玻纤", "amount_raw": "45%"},
                ],
                "process": [{"name_raw": "主机", "value_raw": "465"}],
                "notes_raw": "保持黑度",
            }
        ),
        "lexicon.jsonl": _jsonl(
            {
                "term_type": "material",
                "standard_value": "玻纤",
                "aliases": ["玻璃纤维"],
                "source_quality": "confirmed",
            }
        ),
        "provenance.jsonl": _jsonl(
            {
                "formula_id": "formula-1",
                "source_file": "联创/联创配方.xlsx",
                "sheet_name": "G30A",
                "cell_range": "A2:D5",
                "evidence": [
                    "evidence/formula-1-tight.png",
                    "evidence/formula-1-context.png",
                ],
            }
        ),
        "pending_review.jsonl": b"",
        "excluded_files.jsonl": _jsonl(
            {
                "source_file": "联创/合同.pdf",
                "reason": "NON_FORMULA_DOCUMENT",
            }
        ),
        "validation_report.json": json.dumps(
            {"status": "PASS", "errors": [], "warnings": []}
        ).encode(),
        "evidence/formula-1-tight.png": b"\x89PNG\r\n\x1a\nTIGHT",
        "evidence/formula-1-context.png": b"\x89PNG\r\n\x1a\nCONTEXT",
    }


def _write_package(
    path: Path,
    *,
    mutate: Callable[[dict[str, bytes]], None] | None = None,
    special_members: list[zipfile.ZipInfo] | None = None,
) -> Path:
    members = _valid_members()
    if mutate:
        mutate(members)
    declared = [
        {
            "path": name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        for name, content in sorted(members.items())
    ]
    manifest = {
        "schema_version": "daily-record-knowledge-package-v1",
        "package_id": "test-package",
        "created_at": "2026-07-27T09:00:00Z",
        "files": declared,
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
    ).encode()
    checksums = {
        "manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
        **{item["path"]: item["sha256"] for item in declared},
    }
    checksum_bytes = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(checksums.items())
    ).encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("checksums.sha256", checksum_bytes)
        for name, content in members.items():
            archive.writestr(name, content)
        for info in special_members or []:
            archive.writestr(info, b"link")
    return path


def _replace_member(path: Path, name: str, content: bytes) -> None:
    rewritten = path.with_suffix(".rewritten.zip")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(
        rewritten,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as target:
        for info in source.infolist():
            payload = content if info.filename == name else source.read(info)
            target.writestr(info, payload)
    rewritten.replace(path)


def test_valid_package_returns_immutable_preview(tmp_path: Path) -> None:
    package = _write_package(tmp_path / "valid.zip")

    preview = validate_knowledge_package(package, tmp_path / "previews")

    assert preview.package_id == "test-package"
    assert preview.formula_count == 1
    assert preview.lexicon_count == 1
    assert preview.evidence_count == 2
    assert preview.staging_dir.is_dir()
    with pytest.raises(AttributeError):
        preview.package_id = "changed"  # type: ignore[misc]


def test_missing_referenced_evidence_is_rejected(tmp_path: Path) -> None:
    def remove_evidence(members: dict[str, bytes]) -> None:
        members.pop("evidence/formula-1-tight.png")

    package = _write_package(tmp_path / "missing.zip", mutate=remove_evidence)

    with pytest.raises(KnowledgePackageError, match="evidence"):
        validate_knowledge_package(package, tmp_path / "previews")


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    package = _write_package(tmp_path / "bad-hash.zip")
    _replace_member(
        package,
        "evidence/formula-1-tight.png",
        b"\x89PNG\r\n\x1a\nWRONG",
    )

    with pytest.raises(KnowledgePackageError, match="checksum"):
        validate_knowledge_package(package, tmp_path / "previews")


def test_undeclared_member_is_rejected(tmp_path: Path) -> None:
    info = zipfile.ZipInfo("secret.txt")
    package = _write_package(
        tmp_path / "undeclared.zip",
        special_members=[info],
    )

    with pytest.raises(KnowledgePackageError, match="undeclared"):
        validate_knowledge_package(package, tmp_path / "previews")


@pytest.mark.parametrize("unsafe_name", ["/absolute.txt", "../escape.txt"])
def test_unsafe_paths_are_rejected(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    info = zipfile.ZipInfo(unsafe_name)
    package = _write_package(tmp_path / "unsafe.zip", special_members=[info])

    with pytest.raises(KnowledgePackageError, match="unsafe"):
        validate_knowledge_package(package, tmp_path / "previews")


def test_duplicate_member_is_rejected(tmp_path: Path) -> None:
    package = _write_package(tmp_path / "duplicate.zip")
    with pytest.warns(UserWarning, match="Duplicate"):
        with zipfile.ZipFile(package, "a") as archive:
            archive.writestr("formulas.jsonl", b"{}\n")

    with pytest.raises(KnowledgePackageError, match="duplicate"):
        validate_knowledge_package(package, tmp_path / "previews")


def test_symlink_member_is_rejected(tmp_path: Path) -> None:
    info = zipfile.ZipInfo("evidence/link.png")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    package = _write_package(tmp_path / "symlink.zip", special_members=[info])

    with pytest.raises(KnowledgePackageError, match="symlink"):
        validate_knowledge_package(package, tmp_path / "previews")


def test_invalid_jsonl_is_rejected(tmp_path: Path) -> None:
    def break_json(members: dict[str, bytes]) -> None:
        members["formulas.jsonl"] = b"{broken\n"

    package = _write_package(tmp_path / "invalid-jsonl.zip", mutate=break_json)

    with pytest.raises(KnowledgePackageError, match="JSONL"):
        validate_knowledge_package(package, tmp_path / "previews")


def test_invalid_formula_marker_is_rejected(tmp_path: Path) -> None:
    def break_marker(members: dict[str, bytes]) -> None:
        record = json.loads(members["formulas.jsonl"])
        record["record_type"] = "FAILED"
        members["formulas.jsonl"] = _jsonl(record)

    package = _write_package(tmp_path / "bad-marker.zip", mutate=break_marker)

    with pytest.raises(KnowledgePackageError, match="record_type"):
        validate_knowledge_package(package, tmp_path / "previews")


def test_amount_normalization_is_forbidden(tmp_path: Path) -> None:
    def add_normalized_amount(members: dict[str, bytes]) -> None:
        record = json.loads(members["formulas.jsonl"])
        record["materials"][0]["normalized_amount"] = 55
        members["formulas.jsonl"] = _jsonl(record)

    package = _write_package(tmp_path / "normalized.zip", mutate=add_normalized_amount)

    with pytest.raises(KnowledgePackageError, match="normalized_amount"):
        validate_knowledge_package(package, tmp_path / "previews")


def test_database_changes_only_after_explicit_preview_commit(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "commit.zip")
    data_dir = tmp_path / "data"
    database = data_dir / "knowledge.sqlite3"
    service = KnowledgePackageService(database, data_dir)

    preview = service.validate(package)

    assert not database.exists()
    summary = service.commit_preview(preview.preview_id)
    assert summary.formulas_imported == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM formulas"
        ).fetchone()[0] == 1
        evidence_path = connection.execute(
            "SELECT relative_path FROM formula_evidence LIMIT 1"
        ).fetchone()[0]
    assert evidence_path.startswith(
        f"personal_imports/previews/{preview.preview_id}/evidence/"
    )
