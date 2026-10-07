"""페이스북 페이지(릴스) + 인스타그램(릴스) 업로드. 둘 다 페이지 토큰 사용."""
import os

import requests

from ..config import load_tokens
from . import UploadError, check, wait_until


def _ver(cfg):
    return cfg.get("meta", {}).get("graph_version", "v23.0")


def _graph(cfg):
    return f"https://graph.facebook.com/{_ver(cfg)}"


def _rupload(url: str, token: str, path) -> None:
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        r = requests.post(
            url,
            headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
            data=f,
            timeout=3600,
        )
    check(r)


def _account(section: str, account: str) -> dict:
    info = load_tokens().get(section, {}).get(account)
    if not info:
        raise UploadError(f"{account} 계정의 {section} 연결 정보가 없습니다. setup meta 를 실행하세요.")
    return info


# ── 인스타그램 릴스 ─────────────────────────────────────────────
def upload_instagram(cfg: dict, account: str, path, caption: str) -> str:
    info = _account("instagram", account)
    g, token, ig = _graph(cfg), info["token"], info["ig_id"]
    r = requests.post(
        f"{g}/{ig}/media",
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "share_to_feed": "true",
            "access_token": token,
        },
        timeout=60,
    )
    container = check(r)
    _rupload(container["uri"], token, path)

    def status():
        d = check(requests.get(f"{g}/{container['id']}", params={"fields": "status_code,status", "access_token": token}, timeout=30))
        return d.get("status_code"), d.get("status")

    wait_until(status, done={"FINISHED"}, failed={"ERROR", "EXPIRED"}, timeout=900)
    pub = check(requests.post(f"{g}/{ig}/media_publish", data={"creation_id": container["id"], "access_token": token}, timeout=60))
    try:
        link = check(requests.get(f"{g}/{pub['id']}", params={"fields": "permalink", "access_token": token}, timeout=30))
        return link.get("permalink") or pub["id"]
    except Exception:
        return pub["id"]


# ── 페이스북 페이지 릴스 (실패하면 일반 동영상으로) ────────────────
def upload_facebook(cfg: dict, account: str, path, caption: str) -> str:
    info = _account("facebook", account)
    g, token, page = _graph(cfg), info["page_token"], info["page_id"]
    try:
        start = check(requests.post(f"{g}/{page}/video_reels", data={"upload_phase": "start", "access_token": token}, timeout=60))
        vid = start["video_id"]
        _rupload(start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{_ver(cfg)}/{vid}", token, path)
        check(
            requests.post(
                f"{g}/{page}/video_reels",
                data={
                    "upload_phase": "finish",
                    "video_id": vid,
                    "video_state": "PUBLISHED",
                    "description": caption,
                    "access_token": token,
                },
                timeout=120,
            )
        )
        return f"https://www.facebook.com/reel/{vid}"
    except UploadError as reels_err:
        # 릴스 조건(세로/길이)에 안 맞으면 일반 동영상으로 게시
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    f"https://graph-video.facebook.com/{_ver(cfg)}/{page}/videos",
                    data={"description": caption, "access_token": token},
                    files={"source": (os.path.basename(path), f)},
                    timeout=3600,
                )
            d = check(r)
            return f"https://www.facebook.com/{page}/videos/{d['id']}"
        except UploadError as video_err:
            raise UploadError(f"릴스 실패({reels_err}) / 일반영상 실패({video_err})")
