"""Fail-closed validation and staging for AI-produced knowledge ZIP files."""

from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from .import_models import (
    ExtractionIssue,
    FormulaCandidate,
    LexiconTermCandidate,
    MaterialCandidate,
    ProcessParameterCandidate,
    SourceSpan,
)
from .import_records import FormulaSourceRecord, deduplicate_formulas
from .import_service import (
    ImportSummary,
    PersonalImportBatch,
    PersonalImportService,
    StagedIssue,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "schema"
    / "knowledge-package-v1.schema.json"
)
SCHEMA_VERSION = "daily-record-knowledge-package-v1"
CONTROL_FILES = {"manifest.json", "checksums.sha256"}
JSONL_FILES = {
    "formulas.jsonl",
    "lexicon.jsonl",
    "provenance.jsonl",
    "pending_review.jsonl",
    "excluded_files.jsonl",
}
REQUIRED_FILES = CONTROL_FILES | JSONL_FILES | {"validation_report.json"}
MAX_MEMBERS = 10_000
MAX_MEMBER_SIZE = 512 * 1024 * 1024
MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024


class KnowledgePackageError(ValueError):
    """Raised when a knowledge package fails any security or data gate."""


@dataclass(frozen=True)
class KnowledgePackagePreview:
    preview_id: str
    package_id: str
    package_sha256: str
    staging_dir: Path
    formula_count: int
    lexicon_count: int
    pending_count: int
    excluded_count: int
    evidence_count: int


class KnowledgePackageService:
    """Keep validation read-only and require an explicit preview commit."""

    def __init__(self, database_path: Path, data_root: Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.data_root = Path(data_root).resolve()
        self.preview_root = (
            self.data_root / "personal_imports" / "previews"
        )
        if self.database_path.parent != self.data_root:
            raise ValueError("database_path must be directly inside data_root")

    def validate(self, archive_path: Path) -> KnowledgePackagePreview:
        return validate_knowledge_package(archive_path, self.preview_root)

    def commit_preview(self, preview_id: str) -> ImportSummary:
        if (
            len(preview_id) != 64
            or any(char not in "0123456789abcdef" for char in preview_id)
        ):
            raise KnowledgePackageError("invalid preview_id")
        preview_dir = (self.preview_root / preview_id).resolve()
        if preview_dir.parent != self.preview_root:
            raise KnowledgePackageError("unsafe preview path")
        batch = _batch_from_staged_preview(
            preview_dir,
            self.data_root,
        )
        service = PersonalImportService(self.database_path)
        try:
            return service.import_batch(batch)
        finally:
            service.close()


def validate_knowledge_package(
    archive_path: Path,
    staging_root: Path,
) -> KnowledgePackagePreview:
    """Validate an archive completely, then extract it into immutable staging."""
    archive_path = Path(archive_path).resolve()
    staging_root = Path(staging_root).resolve()
    package_sha256 = _file_sha256(archive_path)

    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise KnowledgePackageError("invalid ZIP archive") from exc

    with archive:
        infos = _validate_zip_metadata(archive.infolist())
        members = set(infos)
        missing_required = REQUIRED_FILES - members
        if missing_required:
            raise KnowledgePackageError(
                f"missing required files: {sorted(missing_required)}"
            )

        manifest_bytes = _read_member(archive, infos["manifest.json"])
        manifest = _load_json_object(manifest_bytes, "manifest.json")
        _validate_manifest(manifest)
        declared = _declared_files(manifest)
        payload_members = members - CONTROL_FILES
        undeclared = payload_members - set(declared)
        missing_declared = set(declared) - payload_members
        if undeclared:
            raise KnowledgePackageError(
                f"undeclared ZIP members: {sorted(undeclared)}"
            )
        if missing_declared:
            raise KnowledgePackageError(
                f"declared files missing from ZIP: {sorted(missing_declared)}"
            )

        checksum_bytes = _read_member(
            archive,
            infos["checksums.sha256"],
        )
        checksums = _parse_checksums(checksum_bytes)
        expected_checksum_paths = {"manifest.json", *declared}
        if set(checksums) != expected_checksum_paths:
            raise KnowledgePackageError(
                "checksums.sha256 paths do not match the manifest"
            )
        if checksums["manifest.json"] != _bytes_sha256(manifest_bytes):
            raise KnowledgePackageError("manifest checksum mismatch")

        payloads: dict[str, bytes] = {}
        for path, declaration in declared.items():
            info = infos[path]
            if info.file_size != declaration["size"]:
                raise KnowledgePackageError(f"size mismatch for {path}")
            content = _read_member(archive, info)
            digest = _bytes_sha256(content)
            if digest != declaration["sha256"] or digest != checksums[path]:
                raise KnowledgePackageError(f"checksum mismatch for {path}")
            payloads[path] = content

        records = {
            path: _parse_jsonl(payloads[path], path)
            for path in JSONL_FILES
        }
        _validate_records(records, payloads)
        report = _load_json_object(
            payloads["validation_report.json"],
            "validation_report.json",
        )
        if report.get("status") != "PASS" or report.get("errors") != []:
            raise KnowledgePackageError(
                "validation_report.json must report PASS with no errors"
            )

        preview_id = package_sha256
        package_id = str(manifest["package_id"])
        staging_dir = staging_root / preview_id
        _stage_validated_archive(
            archive,
            infos,
            staging_root,
            staging_dir,
            package_sha256,
        )

    return KnowledgePackagePreview(
        preview_id=preview_id,
        package_id=package_id,
        package_sha256=package_sha256,
        staging_dir=staging_dir,
        formula_count=len(records["formulas.jsonl"]),
        lexicon_count=len(records["lexicon.jsonl"]),
        pending_count=len(records["pending_review.jsonl"]),
        excluded_count=len(records["excluded_files.jsonl"]),
        evidence_count=sum(
            path.startswith("evidence/") for path in payloads
        ),
    )


def _validate_zip_metadata(
    archive_infos: list[zipfile.ZipInfo],
) -> dict[str, zipfile.ZipInfo]:
    if len(archive_infos) > MAX_MEMBERS:
        raise KnowledgePackageError("ZIP contains too many members")
    infos: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    seen: set[str] = set()
    for info in archive_infos:
        name = info.filename
        if name in seen:
            raise KnowledgePackageError(f"duplicate ZIP member: {name}")
        seen.add(name)
        _validate_member_path(name)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise KnowledgePackageError(f"symlink ZIP member: {name}")
        if info.is_dir():
            continue
        if info.file_size > MAX_MEMBER_SIZE:
            raise KnowledgePackageError(f"ZIP member is too large: {name}")
        total_size += info.file_size
        if total_size > MAX_TOTAL_SIZE:
            raise KnowledgePackageError("ZIP uncompressed size is too large")
        infos[name] = info
    return infos


def _validate_member_path(name: str) -> None:
    if not name or "\x00" in name or "\\" in name:
        raise KnowledgePackageError(f"unsafe ZIP path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise KnowledgePackageError(f"unsafe ZIP path: {name}")
    if path.parts and ":" in path.parts[0]:
        raise KnowledgePackageError(f"unsafe ZIP path: {name}")


def _validate_manifest(manifest: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda error: list(error.path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "manifest"
        raise KnowledgePackageError(
            f"manifest schema error at {location}: {first.message}"
        )
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise KnowledgePackageError("unsupported manifest schema_version")


def _declared_files(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    declared: dict[str, dict[str, Any]] = {}
    for item in manifest["files"]:
        path = item["path"]
        _validate_member_path(path)
        if path in CONTROL_FILES:
            raise KnowledgePackageError(
                f"control file must not be declared: {path}"
            )
        if path in declared:
            raise KnowledgePackageError(
                f"duplicate manifest path: {path}"
            )
        declared[path] = item
    return declared


def _parse_checksums(content: bytes) -> dict[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgePackageError("checksums.sha256 is not UTF-8") from exc
    checksums: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise KnowledgePackageError(
                f"invalid checksum line {number}"
            )
        digest, name = parts
        if (
            len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise KnowledgePackageError(
                f"invalid checksum digest on line {number}"
            )
        _validate_member_path(name)
        if name in checksums:
            raise KnowledgePackageError(
                f"duplicate checksum path: {name}"
            )
        checksums[name] = digest
    return checksums


def _parse_jsonl(content: bytes, path: str) -> tuple[dict[str, Any], ...]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgePackageError(f"{path} is not UTF-8 JSONL") from exc
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise KnowledgePackageError(
                f"invalid JSONL in {path} line {number}"
            ) from exc
        if not isinstance(record, dict):
            raise KnowledgePackageError(
                f"JSONL record must be an object in {path} line {number}"
            )
        records.append(record)
    return tuple(records)


def _validate_records(
    records: dict[str, tuple[dict[str, Any], ...]],
    payloads: dict[str, bytes],
) -> None:
    formula_ids: set[str] = set()
    for record in records["formulas.jsonl"]:
        _validate_formula(record)
        formula_id = record["formula_id"]
        if formula_id in formula_ids:
            raise KnowledgePackageError(
                f"duplicate formula_id: {formula_id}"
            )
        formula_ids.add(formula_id)

    evidence_references: set[str] = set()
    provenance_ids: set[str] = set()
    for record in records["provenance.jsonl"]:
        _require_fields(
            record,
            {
                "formula_id",
                "source_file",
                "sheet_name",
                "cell_range",
                "evidence",
            },
            "provenance",
        )
        formula_id = _non_empty_string(record["formula_id"], "formula_id")
        if formula_id not in formula_ids:
            raise KnowledgePackageError(
                f"provenance references unknown formula_id: {formula_id}"
            )
        provenance_ids.add(formula_id)
        evidence = record["evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise KnowledgePackageError(
                f"provenance evidence is required for {formula_id}"
            )
        for path in evidence:
            path = _non_empty_string(path, "evidence path")
            _validate_member_path(path)
            if not path.startswith("evidence/") or path not in payloads:
                raise KnowledgePackageError(
                    f"missing evidence member: {path}"
                )
            evidence_references.add(path)
    missing_provenance = formula_ids - provenance_ids
    if missing_provenance:
        raise KnowledgePackageError(
            f"formulas missing provenance: {sorted(missing_provenance)}"
        )
    unreferenced_evidence = {
        path for path in payloads if path.startswith("evidence/")
    } - evidence_references
    if unreferenced_evidence:
        raise KnowledgePackageError(
            f"unreferenced evidence: {sorted(unreferenced_evidence)}"
        )

    for record in records["lexicon.jsonl"]:
        _validate_lexicon(record)
    for record in records["pending_review.jsonl"]:
        _require_fields(record, {"reason", "payload"}, "pending review")
    for record in records["excluded_files.jsonl"]:
        _require_fields(
            record,
            {"source_file", "reason"},
            "excluded file",
        )


def _validate_formula(record: dict[str, Any]) -> None:
    required = {
        "record_type",
        "formula_id",
        "customer",
        "product",
        "record_date",
        "date_status",
        "formula_label",
        "materials",
        "process",
        "notes_raw",
    }
    _require_fields(record, required, "formula")
    if record["record_type"] != "FORMULA":
        raise KnowledgePackageError(
            "formula record_type must equal FORMULA"
        )
    _non_empty_string(record["formula_id"], "formula_id")
    _non_empty_string(record["customer"], "customer")
    _non_empty_string(record["product"], "product")
    if record["date_status"] not in {"KNOWN", "UNKNOWN"}:
        raise KnowledgePackageError("date_status must be KNOWN or UNKNOWN")
    record_date = record["record_date"]
    if record["date_status"] == "KNOWN":
        _non_empty_string(record_date, "record_date")
    elif record_date is not None:
        raise KnowledgePackageError(
            "UNKNOWN date_status requires a null record_date"
        )
    materials = record["materials"]
    if not isinstance(materials, list) or not materials:
        raise KnowledgePackageError("formula materials must not be empty")
    for material in materials:
        if not isinstance(material, dict):
            raise KnowledgePackageError("material must be an object")
        if "normalized_amount" in material:
            raise KnowledgePackageError(
                "normalized_amount is forbidden; preserve amount_raw"
            )
        _require_fields(material, {"name_raw", "amount_raw"}, "material")
        _non_empty_string(material["name_raw"], "material name_raw")
        if not isinstance(material["amount_raw"], str):
            raise KnowledgePackageError(
                "material amount_raw must be a string"
            )
    process = record["process"]
    if not isinstance(process, list):
        raise KnowledgePackageError("formula process must be a list")
    for parameter in process:
        _require_fields(
            parameter,
            {"name_raw", "value_raw"},
            "process parameter",
        )
        _non_empty_string(parameter["name_raw"], "process name_raw")
        if not isinstance(parameter["value_raw"], str):
            raise KnowledgePackageError(
                "process value_raw must be a string"
            )


def _validate_lexicon(record: dict[str, Any]) -> None:
    _require_fields(
        record,
        {
            "term_type",
            "standard_value",
            "aliases",
            "source_quality",
        },
        "lexicon",
    )
    if record["term_type"] not in {
        "customer",
        "product",
        "material",
        "process",
        "note_phrase",
    }:
        raise KnowledgePackageError("invalid lexicon term_type")
    _non_empty_string(record["standard_value"], "standard_value")
    aliases = record["aliases"]
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) for alias in aliases
    ):
        raise KnowledgePackageError("lexicon aliases must be strings")
    if record["source_quality"] not in {
        "reference",
        "candidate",
        "confirmed",
    }:
        raise KnowledgePackageError("invalid lexicon source_quality")


def _require_fields(
    record: Any,
    required: set[str],
    kind: str,
) -> None:
    if not isinstance(record, dict):
        raise KnowledgePackageError(f"{kind} must be an object")
    missing = required - set(record)
    if missing:
        raise KnowledgePackageError(
            f"{kind} missing fields: {sorted(missing)}"
        )


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgePackageError(f"{name} must be a non-empty string")
    return value


def _load_json_object(content: bytes, path: str) -> dict[str, Any]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgePackageError(f"invalid JSON in {path}") from exc
    if not isinstance(payload, dict):
        raise KnowledgePackageError(f"{path} must contain a JSON object")
    return payload


def _stage_validated_archive(
    archive: zipfile.ZipFile,
    infos: dict[str, zipfile.ZipInfo],
    staging_root: Path,
    staging_dir: Path,
    package_sha256: str,
) -> None:
    staging_root.mkdir(parents=True, exist_ok=True)
    marker_path = staging_dir / ".validated-package.json"
    if staging_dir.exists():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KnowledgePackageError(
                "existing preview directory is not validated"
            ) from exc
        if marker.get("package_sha256") != package_sha256:
            raise KnowledgePackageError(
                "existing preview checksum does not match"
            )
        return

    with tempfile.TemporaryDirectory(
        prefix=".knowledge-preview-",
        dir=staging_root,
    ) as temporary_name:
        temporary = Path(temporary_name)
        for name, info in infos.items():
            destination = temporary.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
        (temporary / ".validated-package.json").write_text(
            json.dumps(
                {"package_sha256": package_sha256},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(staging_dir)


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
) -> bytes:
    with archive.open(info) as handle:
        return handle.read(MAX_MEMBER_SIZE + 1)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _batch_from_staged_preview(
    preview_dir: Path,
    data_root: Path,
) -> PersonalImportBatch:
    payloads, manifest = _verify_staged_preview(preview_dir)
    records = {
        path: _parse_jsonl(payloads[path], path)
        for path in JSONL_FILES
    }
    _validate_records(records, payloads)
    provenance_by_formula: dict[str, list[dict[str, Any]]] = {}
    for source in records["provenance.jsonl"]:
        provenance_by_formula.setdefault(
            str(source["formula_id"]),
            [],
        ).append(source)

    source_records: list[FormulaSourceRecord] = []
    for order, record in enumerate(records["formulas.jsonl"], 1):
        formula_id = str(record["formula_id"])
        sources = provenance_by_formula[formula_id]
        first_source = sources[0]
        formula = _formula_candidate(record, first_source, order)
        for source in sources:
            source_formula = replace(
                formula,
                source_span=_source_span(source),
            )
            evidence = [
                str(path) for path in source["evidence"]
            ]
            tight = next(
                (path for path in evidence if "tight" in Path(path).stem),
                evidence[0] if evidence else "",
            )
            context = next(
                (
                    path
                    for path in evidence
                    if "context" in Path(path).stem
                ),
                "",
            )
            source_records.append(
                FormulaSourceRecord(
                    formula=source_formula,
                    source_path=str(source["source_file"]),
                    cell_range=str(source["cell_range"]),
                    tight_evidence=_data_relative_path(
                        preview_dir / tight,
                        data_root,
                    ),
                    context_evidence=(
                        _data_relative_path(
                            preview_dir / context,
                            data_root,
                        )
                        if context
                        else ""
                    ),
                    tight_sha256=_file_sha256(preview_dir / tight),
                    context_sha256=(
                        _file_sha256(preview_dir / context)
                        if context
                        else ""
                    ),
                )
            )

    lexicon = tuple(
        LexiconTermCandidate(
            term_type=record["term_type"],
            value=str(record["standard_value"]),
            source_quality=record["source_quality"],
        )
        for record in records["lexicon.jsonl"]
    )
    pending = tuple(
        StagedIssue(
            source_path="AI_PACKAGE",
            sheet_name="",
            issue=ExtractionIssue(
                reason=str(record["reason"]),
                start_row=0,
                end_row=0,
                details=json.dumps(
                    record["payload"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        for record in records["pending_review.jsonl"]
    )
    exclusions = tuple(
        StagedIssue(
            source_path=str(record["source_file"]),
            sheet_name="",
            issue=ExtractionIssue(
                reason=str(record["reason"]),
                start_row=0,
                end_row=0,
            ),
        )
        for record in records["excluded_files.jsonl"]
    )
    return PersonalImportBatch(
        run_id=str(manifest["package_id"]),
        formulas=deduplicate_formulas(source_records),
        lexicon_terms=lexicon,
        pending=pending,
        exclusions=exclusions,
    )


def _verify_staged_preview(
    preview_dir: Path,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    marker_path = preview_dir / ".validated-package.json"
    if not marker_path.is_file():
        raise KnowledgePackageError("validated preview marker is missing")
    manifest_bytes = (preview_dir / "manifest.json").read_bytes()
    manifest = _load_json_object(manifest_bytes, "manifest.json")
    _validate_manifest(manifest)
    declared = _declared_files(manifest)
    checksums = _parse_checksums(
        (preview_dir / "checksums.sha256").read_bytes()
    )
    if checksums.get("manifest.json") != _bytes_sha256(manifest_bytes):
        raise KnowledgePackageError("staged manifest checksum mismatch")
    payloads: dict[str, bytes] = {}
    for path, declaration in declared.items():
        source = preview_dir.joinpath(*PurePosixPath(path).parts)
        if not source.is_file():
            raise KnowledgePackageError(
                f"staged package member is missing: {path}"
            )
        content = source.read_bytes()
        digest = _bytes_sha256(content)
        if (
            len(content) != declaration["size"]
            or digest != declaration["sha256"]
            or digest != checksums.get(path)
        ):
            raise KnowledgePackageError(
                f"staged package checksum mismatch: {path}"
            )
        payloads[path] = content
    return payloads, manifest


def _formula_candidate(
    record: dict[str, Any],
    source: dict[str, Any],
    source_order: int,
) -> FormulaCandidate:
    return FormulaCandidate(
        customer=str(record["customer"]),
        product=str(record["product"]),
        record_date=record["record_date"],
        date_status=record["date_status"],
        source_order=source_order,
        formula_label=str(record["formula_label"]),
        materials=tuple(
            MaterialCandidate(
                name_raw=str(item["name_raw"]),
                amount_raw=str(item["amount_raw"]),
                column=index,
            )
            for index, item in enumerate(record["materials"], 1)
        ),
        process_parameters=tuple(
            ProcessParameterCandidate(
                name_raw=str(item["name_raw"]),
                value_raw=str(item["value_raw"]),
                column=index,
            )
            for index, item in enumerate(record["process"], 1)
        ),
        notes_raw=str(record["notes_raw"]),
        confidence=1.0,
        source_span=_source_span(source),
    )


def _source_span(source: dict[str, Any]) -> SourceSpan:
    return SourceSpan(
        sheet_name=str(source["sheet_name"]),
        start_row=0,
        end_row=0,
        start_column=0,
        end_column=0,
    )


def _data_relative_path(path: Path, data_root: Path) -> str:
    try:
        return path.resolve().relative_to(data_root.resolve()).as_posix()
    except ValueError as exc:
        raise KnowledgePackageError(
            "preview evidence is outside data_root"
        ) from exc
