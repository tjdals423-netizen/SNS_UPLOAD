@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d %~dp0
if not exist .venv (
  echo Installing for the first time, please wait...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe run.py
echo.
echo Upload bot is running in the background.
echo Check Telegram for the start message. Send /status to see its state.
echo To stop it, run stop_bot.bat
timeout /t 5 >nul
