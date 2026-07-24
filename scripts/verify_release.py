"""Release Gate verifier for v1.0.1."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from doctor import run_doctor

REQUIRED_FILES = [
    "AGENTS.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "config/schema/record-v1.schema.json",
    "config/schema/recheck-v1.schema.json",
    "config/schema/settings-v1.schema.json",
    "docs/AI_AGENT_INSTALL.md",
    "docs/AI_AGENT_CONFIGURE.md",
    "docs/AI_AGENT_UPGRADE.md",
    "docs/RELEASE_CHECKLIST.md",
    "install/install-windows.ps1",
    "install/install-linux.sh",
    "install/install-macos.sh",
    ".github/workflows/ci.yml",
    ".github/workflows/windows-install-smoke.yml",
    ".github/workflows/real-ocr.yml",
    ".github/workflows/release.yml",
]


def verify(*, quick: bool = False, allow_dirty: bool = False) -> dict:
    failures: list[str] = []
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        failures.append(f"缺少发布文件: {', '.join(missing)}")

    from lite_app import __version__

    if __version__ != "1.0.1":
        failures.append(f"lite_app.__version__={__version__}，期望 1.0.1")

    doctor = run_doctor()
    if doctor["state"] == "BROKEN":
        failures.append("doctor 返回 BROKEN")

    if not allow_dirty:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if dirty:
            failures.append("Git 工作区不干净")

    commands = []
    if not quick:
        commands = [
            [sys.executable, "-m", "pytest", "-m", "not real_ocr", "-q"],
            [sys.executable, "-m", "ruff", "check", "lite_app", "tests_lite", "scripts"],
        ]
        for command in commands:
            completed = subprocess.run(command, cwd=ROOT, check=False)
            if completed.returncode:
                failures.append(
                    f"命令失败({completed.returncode}): {' '.join(command)}"
                )

    return {
        "schema_version": "release-verification-v1",
        "version": __version__,
        "doctor_state": doctor["state"],
        "missing_files": missing,
        "commands": [" ".join(command) for command in commands],
        "failures": failures,
        "ready": not failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    report = verify(quick=args.quick, allow_dirty=args.allow_dirty)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
