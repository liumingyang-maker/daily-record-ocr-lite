import json
import subprocess
import sys
from pathlib import Path

import openpyxl

from scripts.import_personal_history import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source_tree(root: Path) -> None:
    customer = root / "联创"
    customer.mkdir(parents=True)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "G30A"
    sheet.append(["G30A", None, "2024-07-12"])
    sheet.append(["配方", "PA6", "玻纤"])
    sheet.append([None, "55", "45"])
    sheet.append(["注意事项", "客户要求保持黑度"])
    workbook.save(customer / "联创.xlsx")
    (root / "__MACOSX").mkdir()
    (root / "__MACOSX" / "._联创.xlsx").write_bytes(b"metadata")
    (root / "说明.pdf").write_bytes(b"%PDF")


def test_scan_only_writes_aggregate_report(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "source"
    _source_tree(source)
    report = tmp_path / "scan.json"
    database = tmp_path / "knowledge.sqlite3"

    exit_code = main(
        [
            "scan",
            "--source",
            str(source),
            "--report",
            str(report),
        ]
    )

    assert exit_code == 0
    assert not database.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload == {
        "candidate_files": 1,
        "excluded_files": 2,
        "total_files": 3,
    }
    assert "联创.xlsx" not in capsys.readouterr().out


def test_stage_builds_evidence_without_writing_database(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_tree(source)
    staging = tmp_path / "staging"
    database = tmp_path / "knowledge.sqlite3"

    exit_code = main(
        [
            "stage",
            "--source",
            str(source),
            "--staging",
            str(staging),
            "--run-id",
            "test-run",
        ]
    )

    assert exit_code == 0
    assert not database.exists()
    preview = json.loads(
        (staging / "preview_summary.json").read_text(encoding="utf-8")
    )
    assert preview["formulas_after_dedupe"] == 1
    assert preview["pending_count"] == 0
    assert len(list((staging / "evidence").glob("*_tight.png"))) == 1
    assert len(list((staging / "evidence").glob("*_context.png"))) == 1


def test_import_writes_validated_personal_database(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_tree(source)
    staging = tmp_path / "staging"
    database = tmp_path / "knowledge.sqlite3"

    exit_code = main(
        [
            "import",
            "--source",
            str(source),
            "--staging",
            str(staging),
            "--database",
            str(database),
            "--run-id",
            "test-run",
        ]
    )

    assert exit_code == 0
    assert database.exists()
    receipt = json.loads(
        (staging / "import_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["formulas_imported"] == 1
    assert receipt["source_count"] == 1


def test_rejects_output_inside_the_source_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_tree(source)

    try:
        main(
            [
                "stage",
                "--source",
                str(source),
                "--staging",
                str(source / "generated"),
                "--run-id",
                "unsafe-run",
            ]
        )
    except ValueError as exc:
        assert "原始资料目录" in str(exc)
    else:
        raise AssertionError("staging inside source must be rejected")


def test_script_path_entry_can_import_the_application(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "import_personal_history.py"),
            "--help",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "构建并导入专属配方知识库" in result.stdout
