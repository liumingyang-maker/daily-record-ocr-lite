#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_OCR=0
PADDLE_COMMAND=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-ocr) SKIP_OCR=1 ;;
    --paddle-install-command) shift; PADDLE_COMMAND="${1:-}" ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done
cd "$ROOT"
python3 -c "import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 12), '需要 Python 3.11 或 3.12'"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [[ "$SKIP_OCR" -eq 1 ]]; then
  echo "警告：已跳过 OCR；只能处于 SETUP_REQUIRED 或显式 Demo。"
elif [[ -n "$PADDLE_COMMAND" ]]; then
  PATH="$ROOT/.venv/bin:$PATH" VIRTUAL_ENV="$ROOT/.venv" bash -c "$PADDLE_COMMAND"
  .venv/bin/python -m pip install "paddleocr>=3.0,<4" "opencv-python-headless>=4.9,<5"
else
  echo "请先核对 PaddlePaddle/PaddleOCR 当前 macOS 与 CPU 架构支持；随后传入 --paddle-install-command。"
  exit 1
fi
if [[ "$SKIP_OCR" -eq 0 ]]; then
  .venv/bin/python -c "import cv2, paddle, paddleocr; paddle.utils.run_check(); print('PaddleOCR', paddleocr.__version__, 'OpenCV', cv2.__version__)"
fi
mkdir -p data/jobs data/cache/ocr data/cache/vision data/models
.venv/bin/python -c "from lite_app.settings import SettingsService; from pathlib import Path; s=SettingsService(Path('data')); s.save(s.load())"
set +e
.venv/bin/python scripts/doctor.py --json --gate
doctor_exit=$?
set -e
if [[ "$doctor_exit" -eq 0 ]]; then
  echo "安装和配置检查完成，当前状态 READY。"
elif [[ "$doctor_exit" -eq 1 ]]; then
  echo "安装公共步骤完成，当前状态 SETUP_REQUIRED。"
  echo "请运行 ./start-macos.command 并访问 /setup 配置视觉模型。"
else
  echo "doctor 返回退出码 $doctor_exit；安装失败。" >&2
  exit 2
fi
