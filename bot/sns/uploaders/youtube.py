import json
import logging
import time

from googleapiclient.http import MediaFileUpload

from .. import watchdog
from ..config import SECRETS_DIR
from ..google_client import youtube_service

log = logging.getLogger(__name__)

# 비공개 영상엔 댓글을 못 달아서, 공개로 바뀌면 그때 다는 대기열
PENDING_PATH = SECRETS_DIR / "youtube_comments.json"
CHECK_EVERY = 60           # 공개 여부 확인 주기(초)
DEFAULT_WAIT_MIN = 20      # 업로드 후 이 시간(분) 안에 공개되면 댓글, 지나면 건너뜀


def upload(cfg: dict, account: str, path, title: str) -> str:
    yt = youtube_service(account)
    body = {
        "snippet": {
            "title": title,
            "description": "",
            "categoryId": str(cfg.get("youtube", {}).get("category_id", "22")),
        },
        "status": {
            "privacyStatus": cfg.get("youtube", {}).get("privacy", "private"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        watchdog.beat()
        _, resp = req.next_chunk()
    return f"https://youtu.be/{resp['id']}"


def _load() -> list:
    if not PENDING_PATH.exists():
        return []
    with open(PENDING_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(items: list) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add_pending(account: str, video_url: str, comment: str) -> None:
    items = _load()
    items.append({"account": account, "video_id": video_url.rsplit("/", 1)[-1], "comment": comment, "added": time.time(), "checked": 0})
    _save(items)


def flush_pending(cfg: dict) -> list[str]:
    """공개로 바뀐 영상에 댓글 달기. 알림 메시지 목록을 돌려줌."""
    items, keep, msgs = _load(), [], []
    if not items:
        return msgs
    now = time.time()
    wait = cfg.get("youtube", {}).get("comment_wait_minutes", DEFAULT_WAIT_MIN) * 60
    for it in items:
        if now - it.get("checked", 0) < CHECK_EVERY:
            keep.append(it)
            continue
        it["checked"] = now
        vid = it["video_id"]
        try:
            yt = youtube_service(it["account"])
            found = yt.videos().list(part="status", id=vid).execute().get("items", [])
            if not found:
                continue  # 영상이 삭제됨
            if found[0]["status"]["privacyStatus"] == "public":
                yt.commentThreads().insert(
                    part="snippet",
                    body={"snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": it["comment"]}}}},
                ).execute()
                msgs.append(f"💬 유튜브 댓글 완료 ({it['account']}) https://youtu.be/{vid}")
                continue
            if now - it["added"] > wait:
                msgs.append(f"ℹ️ {wait // 60:.0f}분 안에 공개되지 않아 유튜브 댓글은 건너뛰었어요. 업로드는 정상입니다 ({it['account']}) https://youtu.be/{vid}")
                continue
        except Exception as e:
            log.warning("유튜브 댓글 처리 실패 %s: %s", vid, e)
            it["errors"] = it.get("errors", 0) + 1
            if it["errors"] >= 5:
                msgs.append(f"❗ 유튜브 댓글 실패 ({it['account']}) https://youtu.be/{vid}: {str(e)[:150]}")
                continue
        keep.append(it)
    _save(keep)
    return msgs
