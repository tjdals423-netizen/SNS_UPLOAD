"""자동 복구.

- 감시자(부모 프로세스)가 실제 봇(자식 프로세스)을 띄우고, 꺼지면 다시 켠다.
- 봇 안에서는 진행 신호(beat)가 일정 시간 끊기면 멈춘 것으로 보고 스스로 종료 → 감시자가 다시 켬.
"""
import logging
import os
import subprocess
import sys
import threading
import time

from . import notify

log = logging.getLogger(__name__)

STUCK_EXIT = 3  # 멈춤 감지로 스스로 종료할 때의 종료 코드
_last = time.monotonic()


def beat() -> None:
    """작업이 진행 중임을 알림. 오래 걸리는 반복문 안에서 수시로 호출."""
    global _last
    _last = time.monotonic()


def start(cfg: dict, host: str) -> None:
    """진행 신호가 끊기면 프로세스를 종료하는 감시 스레드 시작."""
    limit = int(cfg.get("watchdog_minutes", 30)) * 60
    beat()

    def run():
        while True:
            time.sleep(30)
            idle = time.monotonic() - _last
            if idle > limit:
                log.error("%d분 넘게 진행이 없어 봇을 다시 켭니다", idle // 60)
                notify.send(cfg, f"⏱ 업로드 봇이 {int(idle // 60)}분 넘게 멈춰 있어서 자동으로 다시 켭니다 ({host})")
                logging.shutdown()
                os._exit(STUCK_EXIT)

    threading.Thread(target=run, daemon=True).start()


def supervise(cfg: dict, host: str) -> None:
    """봇을 자식 프로세스로 실행하고, 꺼지면 다시 켠다 (끝나지 않음)."""
    restarts = 0
    while True:
        env = dict(os.environ, SNS_RESTARTS=str(restarts))
        started = time.monotonic()
        code = subprocess.call([sys.executable, os.path.abspath(sys.argv[0]), "--child"], env=env)
        lived = time.monotonic() - started
        restarts += 1
        log.warning("봇이 꺼졌습니다 (종료 코드 %s, %d초 실행) → 다시 켭니다", code, lived)
        if code != STUCK_EXIT:
            notify.send(cfg, f"💥 업로드 봇이 갑자기 꺼져서 자동으로 다시 켭니다 ({host}, 종료 코드 {code})")
        # 켜자마자 계속 꺼지면 점점 길게 쉬었다가 재시도 (최대 10분)
        time.sleep(30 if lived > 600 else min(600, 30 * 2 ** min(restarts, 5)))
