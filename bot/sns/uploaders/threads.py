"""쓰레드 영상 게시. 쓰레드는 공개 URL 로만 영상을 받으므로 드라이브 링크를 잠깐 공개로 엶."""
import time

import requests

from ..config import load_tokens, update_token
from ..google_client import PublicLink
from . import UploadError, check, wait_until

API = "https://graph.threads.net/v1.0"
REFRESH_AFTER_DAYS = 7


def _token(account: str) -> dict:
    info = load_tokens().get("threads", {}).get(account)
    if not info:
        raise UploadError(f"{account} 계정의 쓰레드 연결 정보가 없습니다. setup threads 를 실행하세요.")
    # 장기 토큰(60일)을 주기적으로 연장
    if time.time() - info.get("saved_at", 0) > REFRESH_AFTER_DAYS * 86400:
        r = requests.get(
            "https://graph.threads.net/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": info["token"]},
            timeout=30,
        )
        if r.ok and r.json().get("access_token"):
            info = {**info, "token": r.json()["access_token"], "saved_at": time.time()}
            update_token("threads", account, info)
    return info


def upload(cfg: dict, account: str, drive, file_id: str, text: str) -> str:
    info = _token(account)
    uid, token = info["user_id"], info["token"]
    with PublicLink(drive, file_id) as video_url:
        c = check(
            requests.post(
                f"{API}/{uid}/threads",
                data={"media_type": "VIDEO", "video_url": video_url, "text": text, "access_token": token},
                timeout=60,
            )
        )

        def status():
            d = check(requests.get(f"{API}/{c['id']}", params={"fields": "status,error_message", "access_token": token}, timeout=30))
            return d.get("status"), d.get("error_message")

        wait_until(status, done={"FINISHED"}, failed={"ERROR", "EXPIRED"}, timeout=900)
    pub = check(requests.post(f"{API}/{uid}/threads_publish", data={"creation_id": c["id"], "access_token": token}, timeout=60))
    try:
        d = check(requests.get(f"{API}/{pub['id']}", params={"fields": "permalink", "access_token": token}, timeout=30))
        return d.get("permalink") or pub["id"]
    except Exception:
        return pub["id"]
