"""하루 한 번 토큰 점검·연장. 문제가 있으면 무엇을 다시 하면 되는지 알려줌."""
import logging
import time
from datetime import datetime

import requests

from .config import load_tokens
from .google_client import OWNER_SCOPES, YOUTUBE_SCOPES, load_creds
from .uploaders import threads, tiktok

log = logging.getLogger(__name__)
WARN_DAYS = 10


def check_tokens(cfg: dict) -> list[str]:
    """문제 목록(텔레그램으로 보낼 문장들)을 돌려줌. 비어 있으면 모두 정상."""
    issues = []
    tokens = load_tokens()

    # 구글: refresh 해보면 살아있는지 알 수 있음
    try:
        load_creds("owner", OWNER_SCOPES)
    except Exception as e:
        issues.append(f"구글(폼/시트) 연결이 끊겼어요 → setup 1번 ({str(e)[:80]})")
    for key in tokens.get("google", {}):
        if key.startswith("youtube_"):
            try:
                load_creds(key, YOUTUBE_SCOPES)
            except Exception as e:
                issues.append(f"유튜브 {key[8:]} 연결이 끊겼어요 → setup 2번 ({str(e)[:80]})")

    # 페북·인스타: 페이지 토큰은 만료 없음. 다만 90일마다 '데이터 접근'이 끝나서 다시 연결 필요
    m = cfg.get("meta", {})
    g = f"https://graph.facebook.com/{m.get('graph_version', 'v23.0')}"
    for acct, info in tokens.get("facebook", {}).items():
        try:
            d = requests.get(
                f"{g}/debug_token",
                params={"input_token": info["page_token"], "access_token": f"{m['app_id']}|{m['app_secret']}"},
                timeout=30,
            ).json().get("data", {})
            if not d.get("is_valid"):
                issues.append(f"페북·인스타 {acct} 연결이 끊겼어요 → setup 3번")
                continue
            exp = d.get("data_access_expires_at") or 0
            left = (exp - time.time()) / 86400 if exp else None
            if left is not None and left < WARN_DAYS:
                when = datetime.fromtimestamp(exp).strftime("%m/%d")
                issues.append(f"페북·인스타 연결이 {when}에 만료돼요 ({max(left, 0):.0f}일 남음) → 그래프 API 탐색기 토큰으로 setup 3번")
        except Exception as e:
            log.warning("메타 토큰 점검 실패 %s: %s", acct, e)

    # 쓰레드: 60일짜리 → 7일 지나면 자동 연장
    for acct in tokens.get("threads", {}):
        try:
            info = threads._token(acct)
            r = requests.get("https://graph.threads.net/v1.0/me", params={"fields": "id", "access_token": info["token"]}, timeout=30)
            if not r.ok:
                issues.append(f"쓰레드 {acct} 연결이 끊겼어요 → setup 4번")
        except Exception as e:
            issues.append(f"쓰레드 {acct} 점검 실패 → setup 4번 ({str(e)[:80]})")

    # 틱톡: 매일 refresh 해서 살려둠
    for acct, info in tokens.get("tiktok", {}).items():
        try:
            info = tiktok.refresh(cfg, acct, info)
            exp = info.get("refresh_expires_at")
            if exp and (exp - time.time()) / 86400 < WARN_DAYS:
                issues.append(f"틱톡 {acct} 연결이 {datetime.fromtimestamp(exp):%m/%d}에 만료돼요 → setup 5번")
        except Exception as e:
            issues.append(f"틱톡 {acct} 연결이 끊겼어요 → setup 5번 ({str(e)[:80]})")

    return issues
