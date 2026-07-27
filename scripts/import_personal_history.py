"""Scan, stage and import a private legacy formula collection."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lite_app.knowledge.import_service import PersonalImportService
from lite_app.knowledge.legacy_builder import (
    prepare_personal_import,
    scan_summary,
)
from lite_app.knowledge.package import KnowledgePackageService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="构建并导入专属配方知识库",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="只读统计资料边界")
    scan.add_argument("--source", type=Path, required=True)
    scan.add_argument("--report", type=Path, required=True)

    for name in ("stage", "import"):
        command = subparsers.add_parser(name)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--staging", type=Path, required=True)
        command.add_argument("--run-id", required=True)
        if name == "import":
            command.add_argument("--database", type=Path, required=True)
    validate_package = subparsers.add_parser("validate-package")
    validate_package.add_argument("--package", type=Path, required=True)
    validate_package.add_argument("--data-dir", type=Path, required=True)
    validate_package.add_argument("--report", type=Path, required=True)
    commit_package = subparsers.add_parser("commit-package")
    commit_package.add_argument("--preview-id", required=True)
    commit_package.add_argument("--data-dir", type=Path, required=True)
    commit_package.add_argument("--database", type=Path, required=True)
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    if args.command == "scan":
        summary = scan_summary(args.source)
        _write_json(args.report, summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "validate-package":
        service = KnowledgePackageService(
            args.data_dir / "knowledge.sqlite3",
            args.data_dir,
        )
        preview = service.validate(args.package)
        payload = asdict(preview)
        payload["staging_dir"] = str(preview.staging_dir)
        _write_json(args.report, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "commit-package":
        service = KnowledgePackageService(
            args.database,
            args.data_dir,
        )
        summary = asdict(service.commit_preview(args.preview_id))
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0

    prepared = prepare_personal_import(
        args.source,
        args.staging,
        args.run_id,
    )
    if args.command == "stage":
        print(
            json.dumps(
                prepared.preview,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    source = args.source.resolve()
    database = args.database.resolve()
    if database == source or database.is_relative_to(source):
        raise ValueError("数据库不能位于原始资料目录内")
    service = PersonalImportService(database)
    try:
        summary = service.import_batch(prepared.batch)
    finally:
        service.close()
    receipt = asdict(summary)
    _write_json(args.staging / "import_receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
