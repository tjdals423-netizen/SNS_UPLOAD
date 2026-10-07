"""텔레그램 알림."""
import logging

import requests

from .config import load_tokens

log = logging.getLogger(__name__)


def send(cfg: dict, text: str) -> None:
    token = (cfg.get("telegram") or {}).get("bot_token")
    chat_id = load_tokens().get("telegram", {}).get("chat_id")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
    except Exception as e:
        log.warning("텔레그램 전송 실패: %s", e)
