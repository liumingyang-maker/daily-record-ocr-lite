@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run install\install-windows.ps1 first.
  exit /b 2
)
".venv\Scripts\python.exe" scripts\doctor.py --json --gate > data\last-doctor.json
if errorlevel 1 (
  type data\last-doctor.json
  echo Doctor reports BROKEN. Application was not started.
  exit /b 2
)
start "" http://127.0.0.1:8765
".venv\Scripts\python.exe" -m lite_app.main
