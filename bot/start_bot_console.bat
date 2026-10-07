@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
rem Runs with a visible window (for checking errors). Close the window to stop.
.venv\Scripts\python.exe run.py
pause
