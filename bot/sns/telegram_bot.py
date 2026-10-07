"""텔레그램 명령(/status 등) 받기. 봇 본체와 따로 도는 스레드."""
import logging
import threading
import time

import requests

from .config import load_tokens
from . import notify

log = logging.getLogger(__name__)

COMMANDS = [
    ("status", "봇 상태와 최근 업로드 보기"),
    ("help", "명령어 목록"),
]


class CommandListener(threading.Thread):
    def __init__(self, cfg: dict, handlers: dict):
        super().__init__(daemon=True)
        self.cfg, self.handlers = cfg, handlers
        self.token = (cfg.get("telegram") or {}).get("bot_token")

    def _api(self, method: str, **params):
        r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params, timeout=70)
        return r.json()

    def run(self) -> None:
        chat_id = load_tokens().get("telegram", {}).get("chat_id")
        if not self.token or not chat_id:
            return
        try:
            # 입력창에 '/' 치면 명령어 목록이 뜨도록 등록
            self._api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
            # 봇이 꺼져 있던 동안 쌓인 메시지는 무시
            old = self._api("getUpdates", offset=-1, timeout=0).get("result", [])
            offset = old[-1]["update_id"] + 1 if old else None
        except Exception as e:
            log.warning("텔레그램 명령 준비 실패: %s", e)
            offset = None

        while True:
            try:
                res = self._api("getUpdates", offset=offset, timeout=50, allowed_updates=["message"])
                for u in res.get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message") or {}
                    if msg.get("chat", {}).get("id") != chat_id:
                        continue  # 내 대화방(그룹) 말고는 무시
                    text = (msg.get("text") or "").strip()
                    if not text.startswith("/"):
                        continue
                    cmd = text.split()[0][1:].split("@")[0].lower()
                    handler = self.handlers.get(cmd) or self.handlers.get("help")
                    try:
                        notify.send(self.cfg, handler())
                    except Exception as e:
                        log.exception("명령 처리 실패: %s", cmd)
                        notify.send(self.cfg, f"❗ /{cmd} 처리 실패: {str(e)[:200]}")
            except Exception as e:
                log.warning("텔레그램 명령 수신 오류: %s", e)
                time.sleep(10)


def help_text() -> str:
    return "📖 사용할 수 있는 명령어\n" + "\n".join(f"/{c} — {d}" for c, d in COMMANDS)
