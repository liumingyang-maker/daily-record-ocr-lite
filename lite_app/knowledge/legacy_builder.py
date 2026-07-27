"""Build a private staged import from read-only legacy workbook sources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .evidence_renderer import render_formula_evidence
from .formula_extractor import extract_sheet
from .import_models import ExtractionIssue
from .import_records import (
    FormulaSourceRecord,
    deduplicate_formulas,
)
from .import_service import PersonalImportBatch, StagedIssue
from .source_scanner import SourceDecision, scan_sources
from .workbook_reader import read_workbook


@dataclass(frozen=True)
class PreparedPersonalImport:
    batch: PersonalImportBatch
    preview: dict[str, int | str]
    source_decisions: tuple[SourceDecision, ...]


def prepare_personal_import(
    source_root: Path,
    staging_dir: Path,
    run_id: str,
) -> PreparedPersonalImport:
    """Read sources, render evidence and return a database-ready batch."""
    source = Path(source_root).resolve()
    staging = Path(staging_dir).resolve()
    _validate_output_boundary(source, staging)
    if not run_id.strip():
        raise ValueError("run_id 不能为空")
    staging.mkdir(parents=True, exist_ok=True)
    evidence_dir = staging / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    decisions = tuple(scan_sources(source))
    formula_sources: list[FormulaSourceRecord] = []
    lexicon_terms = []
    pending: list[StagedIssue] = []
    exclusions: list[StagedIssue] = []
    workbooks_read = 0
    worksheet_count = 0

    for decision in decisions:
        relative = decision.path.as_posix()
        if decision.action != "candidate":
            exclusions.append(
                StagedIssue(
                    relative,
                    "",
                    ExtractionIssue(decision.reason, 0, 0),
                )
            )
            continue
        try:
            workbook = read_workbook(source / decision.path)
        except Exception as exc:
            exclusions.append(
                StagedIssue(
                    relative,
                    "",
                    ExtractionIssue(
                        "WORKBOOK_READ_ERROR",
                        0,
                        0,
                        type(exc).__name__,
                    ),
                )
            )
            continue
        workbooks_read += 1
        for sheet in workbook.sheets:
            worksheet_count += 1
            result = extract_sheet(sheet, decision.customer_hint)
            lexicon_terms.extend(result.lexicon_terms)
            pending.extend(
                StagedIssue(relative, sheet.name, issue)
                for issue in result.pending
            )
            exclusions.extend(
                StagedIssue(relative, sheet.name, issue)
                for issue in result.exclusions
            )
            for formula in result.formulas:
                rendered = render_formula_evidence(
                    sheet,
                    formula,
                    evidence_dir,
                    source_id=f"{relative}\0{sheet.name}\0"
                    f"{formula.source_span.start_row}",
                )
                formula_sources.append(
                    FormulaSourceRecord(
                        formula=formula,
                        source_path=relative,
                        cell_range=(
                            f"{sheet.name}!{rendered.tight_range}"
                        ),
                        tight_evidence=_relative_to_staging(
                            rendered.tight_path,
                            staging,
                        ),
                        context_evidence=_relative_to_staging(
                            rendered.context_path,
                            staging,
                        ),
                        tight_sha256=_sha256(rendered.tight_path),
                        context_sha256=_sha256(rendered.context_path),
                    )
                )

    deduplicated = deduplicate_formulas(formula_sources)
    batch = PersonalImportBatch(
        run_id=run_id,
        formulas=deduplicated,
        lexicon_terms=tuple(lexicon_terms),
        pending=tuple(pending),
        exclusions=tuple(exclusions),
    )
    preview: dict[str, int | str] = {
        "run_id": run_id,
        "total_files": len(decisions),
        "candidate_files": sum(
            item.action == "candidate" for item in decisions
        ),
        "excluded_files": sum(
            item.action == "exclude" for item in decisions
        ),
        "workbooks_read": workbooks_read,
        "worksheet_count": worksheet_count,
        "formulas_before_dedupe": len(formula_sources),
        "formulas_after_dedupe": len(deduplicated),
        "duplicate_formulas": len(formula_sources) - len(deduplicated),
        "pending_count": len(pending),
        "exclusion_count": len(exclusions),
        "lexicon_term_occurrences": len(lexicon_terms),
        "evidence_files": len(formula_sources) * 2,
    }
    _write_json_atomic(staging / "preview_summary.json", preview)
    return PreparedPersonalImport(batch, preview, decisions)


def scan_summary(source_root: Path) -> dict[str, int]:
    decisions = scan_sources(Path(source_root))
    return {
        "candidate_files": sum(
            item.action == "candidate" for item in decisions
        ),
        "excluded_files": sum(
            item.action == "exclude" for item in decisions
        ),
        "total_files": len(decisions),
    }


def _validate_output_boundary(source: Path, output: Path) -> None:
    if output == source or output.is_relative_to(source):
        raise ValueError("输出目录不能位于原始资料目录内")
    if source.is_relative_to(output):
        raise ValueError("原始资料目录不能位于输出目录内")


def _relative_to_staging(path: Path, staging: Path) -> str:
    return path.resolve().relative_to(staging.resolve()).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
