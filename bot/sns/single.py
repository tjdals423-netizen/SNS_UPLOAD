"""봇이 한 PC 에서 두 번 켜지지 않게 막기 (PID 파일)."""
import ctypes
import os

from .config import LOG_DIR

PID_FILE = LOG_DIR / "bot.pid"


def pid_alive(pid: int) -> bool:
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


def acquire() -> bool:
    """이미 실행 중이면 False."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text().strip())
            if old != os.getpid() and pid_alive(old):
                return False
        except ValueError:
            pass
    PID_FILE.write_text(str(os.getpid()))
    return True
