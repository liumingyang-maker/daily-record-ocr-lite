"""Fail a CI gate unless a JUnit report contains a real passing test."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def validate_junit(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    failures = sum(
        1
        for case in cases
        if case.find("failure") is not None or case.find("error") is not None
    )
    skipped = sum(1 for case in cases if case.find("skipped") is not None)
    passed = len(cases) - failures - skipped
    report = {
        "tests": len(cases),
        "passed": passed,
        "skipped": skipped,
        "failures": failures,
    }
    if failures or passed < 1:
        raise RuntimeError(
            "JUnit gate requires at least one passing test and zero failures: "
            f"{report}"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assert that a JUnit report is not empty or all-skipped"
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        report = validate_junit(args.path)
    except (OSError, ET.ParseError, RuntimeError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "PASS", **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
