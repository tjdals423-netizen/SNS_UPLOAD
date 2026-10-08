@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d %~dp0
if not exist .venv (
  echo Installing for the first time, please wait...
  python -m venv .venv
)
rem Install/update packages (fast when already up to date)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt
.venv\Scripts\python.exe menu.py
pause
