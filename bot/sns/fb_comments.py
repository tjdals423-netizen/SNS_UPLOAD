"""페북을 앱에서 직접 올릴 때: 새로 올라온 릴스를 찾아 폼의 댓글을 자동으로 달기.

설정에서 facebook 을 disabled_platforms 에 넣었을 때만 동작한다.
릴스와 폼 응답은 (1) 본문 앞부분이 같은지, (2) 같은 계정·가까운 시간인지로 짝을 짓는다.
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta

import requests

from .config import SECRETS_DIR, load_tokens
from .uploaders import meta

log = logging.getLogger(__name__)

STATE_PATH = SECRETS_DIR / "fb_comment_state.json"
CHECK_EVERY = 180                 # 페이지 확인 주기(초)
MATCH_WINDOW = timedelta(hours=12)  # 폼 제출과 릴스 업로드 사이 허용 시간
GIVE_UP_AFTER = timedelta(hours=24)  # 이 시간 안에 짝을 못 찾으면 그 릴스는 건너뜀
_last_check = 0.0


def _load() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(state: dict) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def parse_form_time(s: str):
    """구글 폼 타임스탬프 '2026. 10. 12 오후 3:54:26' → datetime (PC 현지 시간)."""
    m = re.match(r"\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*(오전|오후)\s*(\d{1,2}):(\d{2}):(\d{2})", s or "")
    if not m:
        return None
    y, mo, d, ap, h, mi, se = m.groups()
    h = int(h) % 12 + (12 if ap == "오후" else 0)
    return datetime(int(y), int(mo), int(d), h, int(mi), int(se))


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")[:30]


def _page_already_commented(g: str, reel_id: str, info: dict) -> bool:
    try:
        cs = requests.get(
            f"{g}/{reel_id}/comments",
            params={"fields": "from", "limit": 50, "access_token": info["page_token"]},
            timeout=30,
        ).json().get("data", [])
        return any((c.get("from") or {}).get("id") == info["page_id"] for c in cs)
    except Exception:
        return False


def run(cfg: dict, rows: list, build_comment) -> list[str]:
    """새 페북 릴스에 댓글 달기. 텔레그램 알림 문장 목록을 돌려줌."""
    global _last_check
    if "facebook" not in (cfg.get("disabled_platforms") or []):
        return []  # 봇이 페북에 직접 올리는 중이면 거기서 이미 댓글을 담
    if time.time() - _last_check < CHECK_EVERY:
        return []
    _last_check = time.time()

    state = _load()
    now = datetime.now()
    # 처음 켤 때는 최근 12시간 릴스부터 (이미 댓글 있는 건 위에서 건너뜀)
    since = datetime.fromisoformat(state.setdefault("since", (now - MATCH_WINDOW).isoformat(timespec="seconds")))
    done = set(state.setdefault("done", []))
    used = set(state.setdefault("used_rows", []))

    cols = cfg["sheet"]["columns"]
    labels = cfg.get("account_labels", {})
    # 댓글이 있는 폼 응답만 후보
    cands = []
    for r in rows:
        acct = labels.get(r.values.get(cols["account"], "").strip())
        comment = build_comment(cfg, r.values.get(cols.get("comment", "댓글"), ""))
        ts = parse_form_time(r.values.get("타임스탬프", ""))
        if acct and comment and ts and r.number not in used and now - ts < GIVE_UP_AFTER + MATCH_WINDOW:
            cands.append({"row": r.number, "acct": acct, "comment": comment, "ts": ts, "body": _norm(r.values.get(cols["body"], ""))})

    msgs = []
    g = f"https://graph.facebook.com/{cfg.get('meta', {}).get('graph_version', 'v23.0')}"
    for acct, info in load_tokens().get("facebook", {}).items():
        try:
            reels = requests.get(
                f"{g}/{info['page_id']}/video_reels",
                params={"fields": "id,created_time,description", "limit": 10, "access_token": info["page_token"]},
                timeout=30,
            ).json().get("data", [])
        except Exception as e:
            log.warning("페북 릴스 확인 실패 %s: %s", acct, e)
            continue
        for reel in reversed(reels):  # 오래된 것부터
            if reel["id"] in done:
                continue
            created = datetime.fromisoformat(reel["created_time"].replace("+0000", "+00:00")).astimezone().replace(tzinfo=None)
            if created < since:
                done.add(reel["id"])  # 이 기능을 켜기 전에 올린 릴스는 건드리지 않음
                continue
            if _page_already_commented(g, reel["id"], info):
                done.add(reel["id"])  # 직접 댓글을 달았거나 이미 단 릴스
                continue
            mine = [c for c in cands if c["acct"] == acct and abs(c["ts"] - created) <= MATCH_WINDOW]
            desc = _norm(reel.get("description", ""))
            match = next((c for c in mine if c["body"] and c["body"] == desc), None)  # 본문이 같으면 확실
            if not match and mine:
                match = min(mine, key=lambda c: abs(c["ts"] - created))  # 아니면 가장 가까운 시간
            if not match:
                if now - created > GIVE_UP_AFTER:
                    done.add(reel["id"])
                continue
            result = meta._comment(cfg, reel["id"], info["page_token"], match["comment"])
            done.add(reel["id"])
            used.add(match["row"])
            cands.remove(match)
            link = f"https://www.facebook.com/reel/{reel['id']}"
            if result.startswith("(댓글✅"):
                msgs.append(f"💬 페북 댓글 완료 ({acct}, 폼 {match['row']}행) {link}")
            else:
                msgs.append(f"❗ 페북 댓글 실패 ({acct}) {link} {result}")

    state["done"] = sorted(done)[-300:]
    state["used_rows"] = sorted(used)[-300:]
    _save(state)
    return msgs
