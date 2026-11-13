"""텔레그램 알림."""
import logging

import requests

from .config import load_tokens

log = logging.getLogger(__name__)


def send(cfg: dict, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
    """buttons = [(글자, 주소)] 를 주면 메시지 아래에 누르면 열리는 버튼."""
    token = (cfg.get("telegram") or {}).get("bot_token")
    chat_id = load_tokens().get("telegram", {}).get("chat_id")
    if not token or not chat_id:
        return
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": [[{"text": t, "url": u}] for t, u in buttons]}
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=body,
            timeout=20,
        )
    except Exception as e:
        log.warning("텔레그램 전송 실패: %s", e)
