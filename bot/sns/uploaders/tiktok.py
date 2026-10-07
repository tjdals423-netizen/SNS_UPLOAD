"""틱톡 Content Posting API.

- inbox (기본): 틱톡 앱 받은편지함(초안)으로 보냄 → 앱에서 본문 붙여넣고 게시. 심사 없이 공개 계정에 사용 가능.
- direct: 바로 게시. 심사 전에는 비공개 계정에만 가능.
"""
import mimetypes
import os
import time

import requests

from ..config import load_tokens, update_token
from . import UploadError, check, wait_until

API = "https://open.tiktokapis.com/v2"
MB = 1024 * 1024


def refresh(cfg: dict, account: str, info: dict) -> dict:
    app = cfg.get("tiktok_app", {})
    d = check(
        requests.post(
            f"{API}/oauth/token/",
            data={
                "client_key": app["client_key"],
                "client_secret": app["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": info["refresh_token"],
            },
            timeout=30,
        )
    )
    info = {
        **info,
        "access_token": d["access_token"],
        "refresh_token": d.get("refresh_token", info["refresh_token"]),
        "expires_at": time.time() + d.get("expires_in", 86400),
    }
    if d.get("refresh_expires_in"):
        info["refresh_expires_at"] = time.time() + d["refresh_expires_in"]
    update_token("tiktok", account, info)
    return info


def _token(cfg, account) -> str:
    info = load_tokens().get("tiktok", {}).get(account)
    if not info:
        raise UploadError(f"{account} 계정의 틱톡 연결 정보가 없습니다. setup tiktok 을 실행하세요.")
    if time.time() > info.get("expires_at", 0) - 300:
        info = refresh(cfg, account, info)
    return info["access_token"]


def upload(cfg: dict, account: str, path, caption: str) -> str:
    token = _token(cfg, account)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    direct = cfg.get("tiktok", {}).get("mode", "inbox") == "direct"

    size = os.path.getsize(path)
    if size <= 64 * MB:
        chunk, count = size, 1
    else:
        chunk = 10 * MB
        count = size // chunk  # 마지막 조각이 나머지를 포함

    source_info = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}
    if direct:
        creator = check(requests.post(f"{API}/post/publish/creator_info/query/", headers=headers, timeout=30))["data"]
        want = cfg.get("tiktok", {}).get("privacy", "SELF_ONLY")
        options = creator.get("privacy_level_options") or [want]
        privacy = want if want in options else ("SELF_ONLY" if "SELF_ONLY" in options else options[0])
        url = f"{API}/post/publish/video/init/"
        body = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": source_info,
        }
    else:
        url = f"{API}/post/publish/inbox/video/init/"
        body = {"source_info": source_info}
    init = check(requests.post(url, headers=headers, json=body, timeout=60))["data"]

    ctype = mimetypes.guess_type(str(path))[0] or "video/mp4"
    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            body = f.read(end - start + 1)
            r = requests.put(
                init["upload_url"],
                headers={"Content-Type": ctype, "Content-Length": str(len(body)), "Content-Range": f"bytes {start}-{end}/{size}"},
                data=body,
                timeout=1800,
            )
            if r.status_code not in (200, 201, 206):
                raise UploadError(f"틱톡 조각 업로드 실패 HTTP {r.status_code}: {r.text[:200]}")

    def status():
        d = check(requests.post(f"{API}/post/publish/status/fetch/", headers=headers, json={"publish_id": init["publish_id"]}, timeout=30))["data"]
        return d.get("status"), d.get("fail_reason")

    wait_until(status, done={"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}, failed={"FAILED"}, timeout=900)
    return f"게시완료({privacy})" if direct else "초안 전송 → 틱톡 앱 알림에서 게시"
