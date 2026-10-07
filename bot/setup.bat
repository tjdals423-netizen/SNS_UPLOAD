@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d %~dp0
if not exist .venv (
  echo 처음 실행: 필요한 프로그램을 설치합니다...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
:menu
echo.
echo ===== 업로드 봇 계정 연결 =====
echo  1. 구글 (폼/시트/드라이브)
echo  2. 유튜브 채널
echo  3. 페이스북 + 인스타
echo  4. 쓰레드
echo  5. 틱톡
echo  6. 텔레그램 알림
echo  7. 연결 상태 점검
echo  0. 종료
set /p n=번호 선택:
if "%n%"=="1" .venv\Scripts\python.exe setup.py google
if "%n%"=="2" .venv\Scripts\python.exe setup.py youtube
if "%n%"=="3" .venv\Scripts\python.exe setup.py meta
if "%n%"=="4" .venv\Scripts\python.exe setup.py threads
if "%n%"=="5" .venv\Scripts\python.exe setup.py tiktok
if "%n%"=="6" .venv\Scripts\python.exe setup.py telegram
if "%n%"=="7" .venv\Scripts\python.exe setup.py check
if "%n%"=="0" exit /b
goto menu
