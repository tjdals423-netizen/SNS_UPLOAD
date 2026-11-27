"""인스타를 직접 올리는 계정 (사용자 지정 2026-11-27: 민아살림·은조네키친·예쁜살림).

봇은 인스타 릴스를 올리지 않고, 텔레그램으로 영상·본문을 보내 준 뒤 사람이 앱에서 올린 릴스를 찾아
고정 댓글(instagram_comment)만 단다. API로 올린 릴스는 앱 음악·기능을 못 써서 직접 올려 보기로 함.

찾는 방법: 그 계정의 최근 게시물 중 대기 등록 10분 전 이후에 올라온 릴스. 대기가 여럿이면 먼저 넣은 것부터
먼저 올라온 릴스에 짝지음. 처음 30분은 2분마다, 그 뒤로는 10분마다, wait_hours(기본 24시간) 안에 안 올라오면 그만.
"""
import json
import logging
import threading
import time
from datetime import datetime

import requests

from .config import SECRETS_DIR, load_tokens
from .uploaders import check
from .uploaders.meta import _comment, _graph

log = logging.getLogger(__name__)

DEFAULT_ACCOUNTS = ["민아살림", "은조네키친", "예쁜살림"]   # config.yaml 에 instagram_manual_accounts 가 없을 때 (예쁜살림 2026-11-27 추가)
PENDING_PATH = SECRETS_DIR / "ig_manual_pending.json"
SLACK_S = 600            # 대기 등록 10분 전에 올라온 릴스까지 인정 (텔레그램 받자마자 올린 경우)
FAST_EVERY, SLOW_EVERY, SLOW_AFTER = 120, 600, 1800
_LOCK = threading.Lock()


def accounts(cfg: dict) -> list[str]:
    v = cfg.get("instagram_manual_accounts")
    return DEFAULT_ACCOUNTS if v is None else list(v)


def is_manual(cfg: dict, account: str) -> bool:
    return account in accounts(cfg)


def wait_hours(cfg: dict) -> float:
    return float(cfg.get("instagram_manual_wait_hours") or 24)


def _load() -> dict:
    if not PENDING_PATH.exists():
        return {"items": [], "used": []}
    with open(PENDING_PATH, encoding="utf-8") as f:
        d = json.load(f)
    return {"items": d.get("items", []), "used": d.get("used", [])}


def _save(d: dict) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    d["used"] = d["used"][-200:]
    tmp = PENDING_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    tmp.replace(PENDING_PATH)


def add(account: str, comment: str, row_no: int) -> None:
    with _LOCK:
        d = _load()
        d["items"].append({"account": account, "comment": comment, "row": row_no, "added": time.time(), "checked": 0})
        _save(d)


def count() -> int:
    return len(_load()["items"])


def _recent_reels(cfg: dict, account: str) -> tuple[list[dict], str]:
    info = load_tokens().get("instagram", {}).get(account)
    if not info:
        raise RuntimeError(f"{account} 인스타 연결 정보가 없어요")
    d = check(requests.get(f"{_graph(cfg)}/{info['ig_id']}/media", params={
        "fields": "id,timestamp,permalink,media_product_type", "limit": 10, "access_token": info["token"]}, timeout=30))
    out = []
    for m in d.get("data", []):
        if m.get("media_product_type") != "REELS":
            continue
        try:
            m["ts"] = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z").timestamp()
        except (KeyError, ValueError):
            continue
        out.append(m)
    return sorted(out, key=lambda m: m["ts"]), info["token"]


def flush(cfg: dict) -> list[str]:
    """직접 올린 릴스를 찾아 댓글. 알림 메시지 목록."""
    with _LOCK:
        d = _load()
    if not d["items"]:
        return []
    now, msgs, limit = time.time(), [], wait_hours(cfg) * 3600
    keep, used = [], set(d["used"])
    by_acc: dict[str, list] = {}
    for it in sorted(d["items"], key=lambda x: x["added"]):
        by_acc.setdefault(it["account"], []).append(it)
    for account, items in by_acc.items():
        every = FAST_EVERY if any(now - it["added"] < SLOW_AFTER for it in items) else SLOW_EVERY
        if now - max(it.get("checked", 0) for it in items) < every:
            keep += items
            continue
        for it in items:
            it["checked"] = now
        try:
            reels, token = _recent_reels(cfg, account)
        except Exception as e:
            log.warning("인스타 직접 올리기 확인 실패 %s: %s", account, e)
            keep += items
            continue
        for it in items:
            m = next((m for m in reels if m["id"] not in used and m["ts"] >= it["added"] - SLACK_S), None)
            if m:
                used.add(m["id"])
                res = _comment(cfg, m["id"], token, it["comment"]) if it["comment"] else ""
                msgs.append(f"💬 {account} 직접 올린 릴스에 댓글 {res} ({it['row']}행)\n{m.get('permalink', '')}")
            elif now - it["added"] > limit:
                msgs.append(f"ℹ️ {account} {it['row']}행: {limit / 3600:.0f}시간 안에 새 릴스가 안 보여서 인스타 댓글은 건너뛰었어요")
            else:
                keep.append(it)
    with _LOCK:
        cur = _load()
        # 확인하는 사이 새로 들어온 대기는 그대로 둠
        seen = {(x["account"], x["added"]) for x in d["items"]}
        keep += [x for x in cur["items"] if (x["account"], x["added"]) not in seen]
        _save({"items": keep, "used": list(used)})
    return msgs
