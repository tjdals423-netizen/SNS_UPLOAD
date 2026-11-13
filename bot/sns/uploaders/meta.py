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
def upload_instagram(cfg: dict, account: str, path, caption: str, comment: str = "", cover_url: str | None = None,
                     drive=None) -> str:
    link, media_id, token, cover_note = _post_instagram(cfg, account, path, caption, cover_url, drive)
    if cover_note:
        link += " " + cover_note
    if comment:
        link += " " + _comment(cfg, media_id, token, comment)
    return link


def _post_instagram(cfg: dict, account: str, path, caption: str, cover_url: str | None = None, drive=None):
    """릴스 올리기. 먼저 파일을 바로 올리고(resumable), 인스타가 'ProcessingFailedError' 로 거절하면
    드라이브에 잠깐 올려 공개 주소(video_url)로 다시 (스토리와 같은 방식).
    (2026-11-12 예쁜살림부터 11-13 민아살림·은조네키친까지 바로 올리기가 계속 거절됨. retriable False 라 기다려도 안 풀림)"""
    from pathlib import Path
    info = _account("instagram", account)
    g, token, ig = _graph(cfg), info["token"], info["ig_id"]
    base = {
        "media_type": "REELS",
        "caption": caption,
        "share_to_feed": "true",
        "access_token": token,
    }

    def make(extra: dict):
        nonlocal cover_note
        data = {**base, **extra}
        if cover_url:
            try:
                c = check(requests.post(f"{g}/{ig}/media", data={**data, "cover_url": cover_url}, timeout=60))
                cover_note = "(썸네일✅)"
                return c
            except UploadError as e:
                # 커버 때문에 막히면 커버 없이라도 올림
                cover_note = f"(썸네일❌ {str(e)[:100]})"
        return check(requests.post(f"{g}/{ig}/media", data=data, timeout=60))

    cover_note = ""
    try:
        container = make({"upload_type": "resumable"})
        _rupload(container["uri"], token, path)
        return _finish_instagram(g, ig, token, container, cover_note)
    except UploadError as e:
        if drive is None or "ProcessingFailed" not in str(e):
            raise
    from ..google_client import PublicLink, temp_drive_file
    with temp_drive_file(drive, Path(path)) as fid, PublicLink(drive, fid) as video_url:
        container = make({"video_url": video_url})
        link, media_id, token, note = _finish_instagram(g, ig, token, container, cover_note)
        return link, media_id, token, (note + " (드라이브 주소로)").strip()


def _finish_instagram(g: str, ig: str, token: str, container: dict, cover_note: str):
    """컨테이너 처리가 끝나길 기다렸다가 게시. (링크, 게시물 id, 토큰, 썸네일 메모)."""
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


# ── 인스타그램 스토리 (사용자 지정 2026-11-10) ──────────────────────
STORY_MAX_S = 59   # 스토리 영상은 60초까지. 넘으면 앞부분만 잘라 올림 (사용자 지정: 앞 59초)


def _duration(ffmpeg: str, path) -> float:
    import re, subprocess
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def _story_file(cfg: dict, path, tmp_dir):
    """60초를 넘으면 앞 max_seconds 초만 다시 인코딩해 임시 파일로 (돌려준 두 번째 값이 True 면 다 쓰고 지움)."""
    import subprocess
    from pathlib import Path
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    limit = float((cfg.get("instagram_story") or {}).get("max_seconds") or STORY_MAX_S)
    if _duration(ffmpeg, path) <= limit + 0.5:
        return Path(path), False
    out = Path(tmp_dir) / f"story_{os.getpid()}_{int(time.time())}.mp4"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path), "-t", f"{limit}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=1200)
    return out, True


def upload_instagram_story(cfg: dict, account: str, path, tmp_dir, drive) -> str:
    """같은 영상을 스토리로 (릴스와 같은 페이지 토큰, media_type=STORIES). 링크 대신 스토리 id.
    스토리는 릴스처럼 파일을 바로 올리면(resumable) 'ProcessingFailedError' 로 거절돼서 (실측 2026-11-10)
    쓰레드처럼 드라이브에 잠깐 올려 공개 주소(video_url)로 넘기고 끝나면 지움."""
    from pathlib import Path
    from ..google_client import PublicLink, temp_drive_file
    info = _account("instagram", account)
    g, token, ig = _graph(cfg), info["token"], info["ig_id"]
    src, temp = _story_file(cfg, path, tmp_dir)
    try:
        with temp_drive_file(drive, Path(src)) as fid, PublicLink(drive, fid) as video_url:
            container = check(requests.post(f"{g}/{ig}/media", data={"media_type": "STORIES", "video_url": video_url,
                                                                      "access_token": token}, timeout=60))

            def status():
                d = check(requests.get(f"{g}/{container['id']}", params={"fields": "status_code,status", "access_token": token}, timeout=30))
                return d.get("status_code"), d.get("status")

            wait_until(status, done={"FINISHED"}, failed={"ERROR", "EXPIRED"}, timeout=900)
            pub = check(requests.post(f"{g}/{ig}/media_publish", data={"creation_id": container["id"], "access_token": token}, timeout=60))
            return f"스토리 {pub['id']}" + (" (앞 59초)" if temp else "")
    finally:
        if temp:
            try:
                os.remove(src)
            except OSError:
                pass


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
