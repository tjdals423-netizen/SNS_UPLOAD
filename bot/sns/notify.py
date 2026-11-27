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


VIDEO_MAX = 49 * 1024 * 1024   # 텔레그램 봇이 보낼 수 있는 파일은 50MB까지


def send_video(cfg: dict, path, caption: str = "") -> str:
    """영상 파일을 텔레그램으로 (폰에 저장해서 직접 올리게). 실패하면 이유 문장, 성공하면 빈 문자열."""
    import os
    token = (cfg.get("telegram") or {}).get("bot_token")
    chat_id = load_tokens().get("telegram", {}).get("chat_id")
    if not token or not chat_id:
        return "텔레그램 설정 없음"
    if os.path.getsize(path) > VIDEO_MAX:
        return f"영상이 {os.path.getsize(path) / 1048576:.0f}MB라 텔레그램으로 못 보내요 (50MB까지)"
    try:
        with open(path, "rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo",
                              data={"chat_id": chat_id, "caption": caption[:1000], "supports_streaming": "true"},
                              files={"video": (os.path.basename(str(path)), f, "video/mp4")}, timeout=600)
        if not r.json().get("ok"):
            return f"텔레그램 영상 전송 실패: {r.text[:150]}"
        return ""
    except Exception as e:
        log.warning("텔레그램 영상 전송 실패: %s", e)
        return f"텔레그램 영상 전송 실패: {e}"
