"""처음 한 번 계정을 연결하는 도구.

  python setup.py google          폼 주인 구글 계정 연결 (드라이브/시트)
  python setup.py youtube         유튜브 채널 연결 (A/B/C 하나씩)
  python setup.py meta            페이스북 페이지 + 인스타 연결 (페이지 관리하는 페북 계정마다)
  python setup.py threads         쓰레드 계정 연결 (A/B/C 하나씩)
  python setup.py tiktok          틱톡 계정 연결 (A/B/C 하나씩)
  python setup.py telegram        텔레그램 알림 연결
  python setup.py check           연결 상태 점검
"""
import sys
import time

import requests

from sns import google_client, notify
from sns.config import load_config, load_tokens, update_token
from sns.oauth_web import ask_code, choose_account


def accounts(cfg):
    return list(dict.fromkeys((cfg.get("account_labels") or {"A": "A", "B": "B", "C": "C"}).values()))


def setup_google(cfg):
    print("폼을 만든 구글 계정으로 로그인하세요. (경고 화면이 뜨면 '고급' → '이동')")
    creds = google_client.login(google_client.OWNER_SCOPES)
    google_client.save_creds("owner", creds)
    print("✅ 구글(드라이브/시트) 연결 완료")


def setup_youtube(cfg):
    acct = choose_account(accounts(cfg))
    print(f"{acct} 계정의 유튜브 채널로 로그인하세요. 채널 선택 화면이 나오면 {acct} 채널을 고르세요.")
    creds = google_client.login(google_client.YOUTUBE_SCOPES)
    google_client.save_creds(f"youtube_{acct}", creds)
    ch = google_client.youtube_service(acct).channels().list(part="snippet", mine=True).execute()
    name = ch["items"][0]["snippet"]["title"] if ch.get("items") else "(채널 없음)"
    print(f"✅ 유튜브 {acct} = '{name}' 연결 완료")


def setup_meta(cfg):
    m = cfg["meta"]
    ver = m.get("graph_version", "v23.0")
    g = f"https://graph.facebook.com/{ver}"
    print(
        "\n[그래프 API 탐색기에서 토큰 받기]\n"
        "1) 브라우저에서 https://developers.facebook.com/tools/explorer 열기\n"
        "2) 오른쪽 'Meta 앱'에서 이 봇용 앱 선택\n"
        "3) '사용자 또는 페이지'는 '사용자 토큰'\n"
        "4) 권한 추가: pages_show_list, pages_read_engagement, pages_manage_posts,\n"
        "   instagram_basic, instagram_content_publish, business_management\n"
        "5) 'Generate Access Token' → 페이지를 모두 체크하고 계속\n"
        "6) 위쪽 '액세스 토큰' 칸의 긴 값을 복사\n"
    )
    short_token = input("복사한 액세스 토큰을 붙여넣고 Enter: ").strip()
    long = requests.get(
        f"{g}/oauth/access_token",
        params={"grant_type": "fb_exchange_token", "client_id": m["app_id"], "client_secret": m["app_secret"], "fb_exchange_token": short_token},
        timeout=30,
    ).json()
    if "access_token" not in long:
        raise SystemExit(f"토큰 변환 실패 (앱 ID/시크릿이 탐색기에서 고른 앱과 같은지 확인): {long}")
    pages = requests.get(
        f"{g}/me/accounts",
        params={"fields": "id,name,access_token,instagram_business_account{id,username}", "access_token": long["access_token"], "limit": 100},
        timeout=30,
    ).json().get("data", [])
    if not pages:
        raise SystemExit("관리 중인 페이지를 찾지 못했습니다. 로그인할 때 페이지 선택 화면에서 페이지를 모두 체크했는지 확인하세요.")
    accts = accounts(cfg)
    for p in pages:
        ig = p.get("instagram_business_account") or {}
        print(f"\n페이지: {p['name']}  /  연결된 인스타: @{ig.get('username', '없음')}")
        ans = input(f"이 페이지는 어느 계정인가요? ({'/'.join(accts)}, 건너뛰려면 Enter): ").strip().upper()
        if ans not in accts:
            continue
        update_token("facebook", ans, {"page_id": p["id"], "page_name": p["name"], "page_token": p["access_token"]})
        if ig.get("id"):
            update_token("instagram", ans, {"ig_id": ig["id"], "username": ig.get("username"), "token": p["access_token"]})
        print(f"✅ {ans} = 페북 '{p['name']}' / 인스타 @{ig.get('username', '없음')}")


def setup_threads(cfg):
    t = cfg["threads"]
    acct = choose_account(accounts(cfg))
    print(f"브라우저에서 {acct} 계정으로 쓰레드에 로그인되어 있는지 먼저 확인하세요.")
    code = ask_code(
        "https://threads.net/oauth/authorize",
        {
            "client_id": t["app_id"],
            "redirect_uri": cfg["redirect_uri"],
            "scope": "threads_basic,threads_content_publish",
            "response_type": "code",
        },
    )
    short = requests.post(
        "https://graph.threads.net/oauth/access_token",
        data={"client_id": t["app_id"], "client_secret": t["app_secret"], "grant_type": "authorization_code", "redirect_uri": cfg["redirect_uri"], "code": code},
        timeout=30,
    ).json()
    if "access_token" not in short:
        raise SystemExit(f"토큰 발급 실패: {short}")
    long = requests.get(
        "https://graph.threads.net/access_token",
        params={"grant_type": "th_exchange_token", "client_secret": t["app_secret"], "access_token": short["access_token"]},
        timeout=30,
    ).json()
    token = long.get("access_token", short["access_token"])
    me = requests.get("https://graph.threads.net/v1.0/me", params={"fields": "id,username", "access_token": token}, timeout=30).json()
    update_token("threads", acct, {"user_id": me["id"], "username": me.get("username"), "token": token, "saved_at": time.time()})
    print(f"✅ 쓰레드 {acct} = @{me.get('username')} 연결 완료")


def setup_tiktok(cfg):
    app = cfg["tiktok_app"]
    acct = choose_account(accounts(cfg))
    print(f"브라우저에서 {acct} 계정으로 틱톡에 로그인되어 있는지 먼저 확인하세요.")
    code = ask_code(
        "https://www.tiktok.com/v2/auth/authorize/",
        {
            "client_key": app["client_key"],
            "redirect_uri": cfg["redirect_uri"],
            "scope": "user.info.basic,video.upload,video.publish",
            "response_type": "code",
        },
    )
    d = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        data={"client_key": app["client_key"], "client_secret": app["client_secret"], "code": code, "grant_type": "authorization_code", "redirect_uri": cfg["redirect_uri"]},
        timeout=30,
    ).json()
    if "access_token" not in d:
        raise SystemExit(f"토큰 발급 실패: {d}")
    info = requests.get(
        "https://open.tiktokapis.com/v2/user/info/",
        params={"fields": "display_name"},
        headers={"Authorization": f"Bearer {d['access_token']}"},
        timeout=30,
    ).json()
    name = (info.get("data") or {}).get("user", {}).get("display_name", "?")
    update_token(
        "tiktok",
        acct,
        {"open_id": d.get("open_id"), "name": name, "access_token": d["access_token"], "refresh_token": d["refresh_token"], "expires_at": time.time() + d.get("expires_in", 86400)},
    )
    print(f"✅ 틱톡 {acct} = '{name}' 연결 완료")


def setup_telegram(cfg):
    token = (cfg.get("telegram") or {}).get("bot_token")
    if not token:
        raise SystemExit("config.yaml 의 telegram.bot_token 을 먼저 채워주세요.")
    input("알림 받을 폰의 텔레그램에서 내 봇에게 아무 메시지(예: 안녕)를 보낸 뒤 Enter: ")
    upd = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
    chats = [u["message"]["chat"] for u in upd.get("result", []) if "message" in u]
    if not chats:
        raise SystemExit("메시지를 찾지 못했습니다. 봇에게 메시지를 보낸 뒤 다시 실행하세요.")
    chat = chats[-1]
    update_token("telegram", "chat_id", chat["id"])
    notify.send(cfg, "✅ 업로드 봇 알림이 연결되었습니다.")
    print(f"✅ 텔레그램 연결 완료 ({chat.get('first_name') or chat.get('title')})")


def check(cfg):
    tokens = load_tokens()
    print("구글(드라이브/시트):", "✅" if tokens.get("google", {}).get("owner") else "❌ python setup.py google")
    for a in accounts(cfg):
        row = [
            "유튜브 " + ("✅" if tokens.get("google", {}).get(f"youtube_{a}") else "❌"),
            "인스타 " + ("✅" if a in tokens.get("instagram", {}) else "❌"),
            "페북 " + ("✅" if a in tokens.get("facebook", {}) else "❌"),
            "쓰레드 " + ("✅" if a in tokens.get("threads", {}) else "❌"),
            "틱톡 " + ("✅" if a in tokens.get("tiktok", {}) else "❌"),
        ]
        print(f"계정 {a}: " + "  ".join(row))
    print("텔레그램:", "✅" if tokens.get("telegram", {}).get("chat_id") else "❌ python setup.py telegram")
    if tokens.get("google", {}).get("owner") and cfg.get("sheet", {}).get("spreadsheet_id"):
        from sns.sheet import Sheet

        _, sheets = google_client.owner_services()
        s = Sheet(sheets, cfg)
        rows = s.read()
        cols = cfg["sheet"]["columns"]
        missing = [c for c in cols.values() if c not in s.headers]
        print(f"시트 '{s.ws}': 응답 {len(rows)}개", "/ ⚠️ 시트에 없는 열: " + ", ".join(missing) if missing else "/ 열 이름 ✅")


COMMANDS = {
    "google": setup_google,
    "youtube": setup_youtube,
    "meta": setup_meta,
    "threads": setup_threads,
    "tiktok": setup_tiktok,
    "telegram": setup_telegram,
    "check": check,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]](load_config())
