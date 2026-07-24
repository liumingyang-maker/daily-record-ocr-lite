"""The real-OCR workflow cannot pass when every test is skipped."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.assert_junit_passed import validate_junit


def _write_report(path: Path, body: str) -> Path:
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    return path


def test_junit_gate_accepts_a_real_pass(tmp_path):
    report = _write_report(
        tmp_path / "passed.xml",
        '<testcase classname="real" name="inference"/>',
    )
    assert validate_junit(report)["passed"] == 1


def test_junit_gate_rejects_all_skipped(tmp_path):
    report = _write_report(
        tmp_path / "skipped.xml",
        '<testcase classname="real" name="inference"><skipped/></testcase>',
    )
    with pytest.raises(RuntimeError, match="at least one passing"):
        validate_junit(report)
