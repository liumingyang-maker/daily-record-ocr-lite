#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[[ -x .venv/bin/python ]] || { echo "缺少 .venv，请先运行安装脚本" >&2; exit 2; }
set +e
.venv/bin/python scripts/doctor.py --json --gate > data/last-doctor.json
doctor_exit=$?
set -e
[[ "$doctor_exit" -eq 0 ]] || { cat data/last-doctor.json; exit 2; }
.venv/bin/python -m lite_app.main
