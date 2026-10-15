"""텔레그램 명령(/status, /upload 등) 받기. 봇 본체와 따로 도는 스레드."""
import logging
import threading
import time

import requests

from .config import load_tokens

log = logging.getLogger(__name__)

COMMANDS = [
    ("upload", "PC 폴더 영상 올리기 (완성본.mp4 + 캡션.txt)"),
    ("status", "봇 상태와 최근 업로드 보기"),
    ("cancel", "진행 중인 /upload 취소"),
    ("help", "명령어 목록"),
]


class CommandListener(threading.Thread):
    def __init__(self, cfg: dict, handlers: dict, upload=None):
        super().__init__(daemon=True)
        self.cfg, self.handlers, self.upload = cfg, handlers, upload
        self.token = (cfg.get("telegram") or {}).get("bot_token")
        self.chat_id = None

    def _api(self, method: str, **params):
        r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params, timeout=70)
        return r.json()

    def _send(self, text: str, markup=None) -> None:
        params = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        if markup:
            params["reply_markup"] = markup
        try:
            self._api("sendMessage", **params)
        except Exception as e:
            log.warning("텔레그램 전송 실패: %s", e)

    def _reply(self, items) -> None:
        for text, markup in items or []:
            self._send(text, markup)

    def _on_message(self, text: str) -> None:
        if text.startswith("/"):
            cmd = text.split()[0][1:].split("@")[0].lower()
            if self.upload and cmd == "upload":
                return self._reply(self.upload.start())
            if self.upload and cmd == "cancel":
                return self._reply(self.upload.cancel())
            handler = self.handlers.get(cmd) or self.handlers.get("help")
            return self._send(handler())
        if self.upload and self.upload.active:
            return self._reply(self.upload.on_text(text))

    def _on_callback(self, cq: dict) -> None:
        try:
            self._api("answerCallbackQuery", callback_query_id=cq["id"])
        except Exception:
            pass
        data = cq.get("data") or ""
        if self.upload and data.startswith("up:"):
            # 누른 버튼은 없애서 두 번 눌리지 않게
            m = cq.get("message") or {}
            try:
                self._api("editMessageReplyMarkup", chat_id=self.chat_id, message_id=m.get("message_id"), reply_markup={"inline_keyboard": []})
            except Exception:
                pass
            self._reply(self.upload.on_callback(data))

    def run(self) -> None:
        self.chat_id = load_tokens().get("telegram", {}).get("chat_id")
        if not self.token or not self.chat_id:
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
                res = self._api("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"])
                for u in res.get("result", []):
                    offset = u["update_id"] + 1
                    try:
                        if "callback_query" in u:
                            cq = u["callback_query"]
                            if (cq.get("message") or {}).get("chat", {}).get("id") == self.chat_id:
                                self._on_callback(cq)
                            continue
                        msg = u.get("message") or {}
                        if msg.get("chat", {}).get("id") != self.chat_id:
                            continue  # 내 대화방(그룹) 말고는 무시
                        self._on_message((msg.get("text") or "").strip())
                    except Exception as e:
                        log.exception("텔레그램 명령 처리 실패")
                        self._send(f"❗ 처리 중 오류: {str(e)[:200]}")
            except Exception as e:
                log.warning("텔레그램 명령 수신 오류: %s", e)
                time.sleep(10)


def help_text() -> str:
    return "📖 사용할 수 있는 명령어\n" + "\n".join(f"/{c} — {d}" for c, d in COMMANDS)
