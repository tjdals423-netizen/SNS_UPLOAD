"""페이스북 페이지(릴스) + 인스타그램(릴스) 업로드. 둘 다 페이지 토큰 사용."""
import os
import time

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
def upload_instagram(cfg: dict, account: str, path, caption: str, comment: str = "", cover_url: str | None = None) -> str:
    link, media_id, token, cover_note = _post_instagram(cfg, account, path, caption, cover_url)
    if cover_note:
        link += " " + cover_note
    if comment:
        link += " " + _comment(cfg, media_id, token, comment)
    return link


def _post_instagram(cfg: dict, account: str, path, caption: str, cover_url: str | None = None):
    info = _account("instagram", account)
    g, token, ig = _graph(cfg), info["token"], info["ig_id"]
    data = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "share_to_feed": "true",
        "access_token": token,
    }
    cover_note = ""
    if cover_url:
        try:
            container = check(requests.post(f"{g}/{ig}/media", data={**data, "cover_url": cover_url}, timeout=60))
            cover_note = "(썸네일✅)"
        except UploadError as e:
            # 커버 때문에 막히면 커버 없이라도 올림
            container = check(requests.post(f"{g}/{ig}/media", data=data, timeout=60))
            cover_note = f"(썸네일❌ {str(e)[:100]})"
    else:
        container = check(requests.post(f"{g}/{ig}/media", data=data, timeout=60))
    _rupload(container["uri"], token, path)

    def status():
        d = check(requests.get(f"{g}/{container['id']}", params={"fields": "status_code,status", "access_token": token}, timeout=30))
        return d.get("status_code"), d.get("status")

    wait_until(status, done={"FINISHED"}, failed={"ERROR", "EXPIRED"}, timeout=900)
    pub = check(requests.post(f"{g}/{ig}/media_publish", data={"creation_id": container["id"], "access_token": token}, timeout=60))
    try:
        link = check(requests.get(f"{g}/{pub['id']}", params={"fields": "permalink", "access_token": token}, timeout=30))
        return link.get("permalink") or pub["id"], pub["id"], token, cover_note
    except Exception:
        return pub["id"], pub["id"], token, cover_note


# ── 페이스북 페이지 릴스 (실패하면 일반 동영상으로) ────────────────
def upload_facebook(cfg: dict, account: str, path, caption: str, comment: str = "", thumb_path=None) -> str:
    link, post_id, token = _post_facebook(cfg, account, path, caption)
    if thumb_path:
        link += " " + _fb_thumbnail(cfg, post_id, token, thumb_path)
    if comment:
        link += " " + _comment(cfg, post_id, token, comment)
    return link


def _fb_thumbnail(cfg: dict, video_id: str, token: str, thumb_path) -> str:
    """올린 영상의 대표 썸네일 지정. 영상 처리 중이면 거절될 수 있어 몇 번 재시도."""
    err = None
    for _ in range(6):
        try:
            with open(thumb_path, "rb") as f:
                check(
                    requests.post(
                        f"{_graph(cfg)}/{video_id}/thumbnails",
                        data={"is_preferred": "true", "access_token": token},
                        files={"source": (os.path.basename(thumb_path), f, "image/jpeg")},
                        timeout=120,
                    )
                )
            return "(썸네일✅)"
        except UploadError as e:
            err = e
            time.sleep(20)
    return f"(썸네일❌ {str(err)[:100]})"


def _comment(cfg: dict, object_id: str, token: str, comment: str) -> str:
    """페북/인스타 공용 댓글. 영상 처리 중이면 거절될 수 있어 몇 번 재시도."""
    err = None
    for _ in range(6):
        try:
            check(requests.post(f"{_graph(cfg)}/{object_id}/comments", data={"message": comment, "access_token": token}, timeout=60))
            return "(댓글✅)"
        except UploadError as e:
            err = e
            time.sleep(20)
    return f"(댓글❌ {str(err)[:120]})"


def _post_facebook(cfg: dict, account: str, path, caption: str):
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
        return f"https://www.facebook.com/reel/{vid}", vid, token
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
            return f"https://www.facebook.com/{page}/videos/{d['id']}", d["id"], token
        except UploadError as video_err:
            raise UploadError(f"릴스 실패({reels_err}) / 일반영상 실패({video_err})")
