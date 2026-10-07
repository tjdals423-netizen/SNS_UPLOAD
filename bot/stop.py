"""백그라운드로 실행 중인 업로드 봇 끄기 (stop_bot.bat 에서 실행)."""
import subprocess

from sns.single import PID_FILE, pid_alive

pid = int(PID_FILE.read_text().strip() or 0) if PID_FILE.exists() else 0
if pid and pid_alive(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    print(f"업로드 봇을 껐습니다. (PID {pid})")
else:
    print("실행 중인 봇이 없습니다.")
PID_FILE.unlink(missing_ok=True)
