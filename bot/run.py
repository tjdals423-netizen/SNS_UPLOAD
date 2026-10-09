"""업로드 봇 본체.

  python run.py          계속 실행 (시트를 주기적으로 확인)
  python run.py --once   한 번만 확인하고 종료
"""
import logging
import os
import re
import socket
import sys
import time
from datetime import datetime, timedelta

from sns import captions, hints, notify, watchdog
from sns.config import PLATFORM_KO, PLATFORMS, TMP_DIR, load_config, setup_logging
from sns.google_client import cleanup, download, download_image_jpeg, file_id_from_url, owner_services, public_image
from sns.sheet import RESULT_COLS, STATUS_COL, Sheet
from sns.uploaders import meta, threads, tiktok, youtube

log = logging.getLogger("bot")
LOCK_TIMEOUT = timedelta(hours=2)
RETRY_AFTER = timedelta(minutes=10)
HOST = socket.gethostname()


def parse_platforms(cfg, raw: str) -> list[str]:
    labels = cfg.get("platform_labels", {})
    out = []
    for part in re.split(r"\s*,\s*", raw or ""):
        p = labels.get(part.strip())
        if p and p not in out:
            out.append(p)
    return [p for p in PLATFORMS if p in out]


def fail_count(cell: str) -> int:
    m = re.match(r"실패(\d+)", cell or "")
    return int(m.group(1)) if m else 0


def retry_due(status: str) -> bool:
    """'일부실패|시각' 이면 마지막 시도 후 RETRY_AFTER 가 지났는지."""
    try:
        return datetime.now() - datetime.fromisoformat(status.split("|")[1]) >= RETRY_AFTER
    except Exception:
        return True


def pending_platforms(cfg, row, platforms) -> list[str]:
    due = retry_due(row.values.get(STATUS_COL, ""))
    todo = []
    for p in platforms:
        cell = row.values.get(RESULT_COLS[p], "")
        if not cell or (due and cell.startswith("실패") and fail_count(cell) < cfg.get("max_retries", 3)):
            todo.append(p)
    return todo


def build_comment(cfg, raw: str) -> str:
    """댓글 칸에 숫자만 쓰면 comment_template 의 {번호} 자리에 넣어줌."""
    raw = (raw or "").strip()
    tpl = cfg.get("comment_template") or ""
    if tpl and raw.isdigit():
        return tpl.replace("{번호}", raw)
    return raw


def is_locked(status: str) -> bool:
    if not status.startswith("처리중"):
        return False
    try:
        _, host, t = status.split("|")[:3]
        ts = datetime.fromisoformat(t)
        if host == HOST and ts < STATE["started"]:
            return False  # 이 PC 의 봇이 재시작되기 전에 하던 건 → 이어서 처리
        return datetime.now() - ts < LOCK_TIMEOUT
    except Exception:
        return False


def process_row(cfg, drive, sheet, row) -> None:
    cols = cfg["sheet"]["columns"]
    v = row.values
    account = cfg.get("account_labels", {}).get(v.get(cols["account"], "").strip())
    platforms = parse_platforms(cfg, v.get(cols["platforms"], ""))
    if not account or not platforms or not v.get(cols["video"]):
        return
    todo = pending_platforms(cfg, row, platforms)
    if not todo or is_locked(v.get(STATUS_COL, "")):
        return

    sheet.write(row, STATUS_COL, f"처리중|{HOST}|{datetime.now().isoformat(timespec='seconds')}")
    log.info("%d행 처리 시작: 계정 %s, %s", row.number, account, ",".join(todo))

    path = None
    file_id = None
    thumb_path = None
    thumb_id = None
    results = {}
    fix_hints = []
    raw_comment = v.get(cols.get("comment", "댓글"), "")
    comment = build_comment(cfg, raw_comment)
    # 인스타는 고정 문구를 항상 사용 (설정이 비어 있으면 공통 댓글)
    ig_comment = (cfg.get("instagram_comment") or "").strip() or comment
    text_for_tiktok = ""
    try:
        file_id = file_id_from_url(v[cols["video"]].split(",")[0])
        path = download(drive, file_id, TMP_DIR)
        raw_thumb = v.get(cols.get("thumbnail", "썸네일"), "")
        if raw_thumb and any(p in todo for p in ("instagram", "facebook")):
            try:
                thumb_id = file_id_from_url(raw_thumb.split(",")[0])
                thumb_path = download_image_jpeg(drive, thumb_id, TMP_DIR)
            except Exception as e:
                log.warning("썸네일 준비 실패: %s", e)
        text = captions.build(
            cfg,
            v.get(cols["yt_title"], ""),
            v.get(cols["body"], ""),
            v.get(cols["tiktok_body"], ""),
            todo,
        )
        text_for_tiktok = text["tiktok"]
        for p in todo:
            watchdog.beat()
            try:
                if p == "youtube":
                    res = youtube.upload(cfg, account, path, text["youtube"])
                    if comment:
                        youtube.add_pending(account, res, comment)
                        res += f" (댓글: {cfg.get('youtube', {}).get('comment_wait_minutes', 20)}분 안에 공개하면 자동)"
                elif p == "instagram":
                    with public_image(drive, thumb_path) as cover_url:
                        res = meta.upload_instagram(cfg, account, path, text["instagram"], ig_comment, cover_url)
                elif p == "facebook":
                    res = meta.upload_facebook(cfg, account, path, text["facebook"], comment, thumb_path)
                elif p == "threads":
                    res = threads.upload(cfg, account, drive, file_id, text["threads"], comment)
                else:
                    res = tiktok.upload(cfg, account, path, text["tiktok"])
                cell = f"완료 {res}"
            except Exception as e:
                log.exception("%s 업로드 실패", p)
                prev = fail_count(row.values.get(RESULT_COLS[p], ""))
                cell = f"실패{prev + 1}: {str(e)[:300]}"
                fix_hints.append(hints.for_failure(p, account, str(e)))
            results[p] = cell
            sheet.write(row, RESULT_COLS[p], cell)
    except Exception as e:
        log.exception("%d행 준비 실패", row.number)
        fix_hints.append(hints.for_failure("google", account, str(e)))
        for p in todo:
            prev = fail_count(row.values.get(RESULT_COLS[p], ""))
            results[p] = f"실패{prev + 1}: {str(e)[:300]}"
            sheet.write(row, RESULT_COLS[p], results[p])
    finally:
        for f in (path, thumb_path):
            if f and f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass

    ok = all(r.startswith("완료") for r in results.values())
    now = datetime.now().isoformat(timespec="seconds")
    sheet.write(row, STATUS_COL, "완료" if ok else f"일부실패|{now}")

    # 모두 끝났으면 드라이브 원본 정리
    mode = cfg.get("drive_cleanup", "delete")
    if ok and mode in ("delete", "trash"):
        for fid in (file_id, thumb_id):
            if not fid:
                continue
            try:
                cleanup(drive, fid, mode)
            except Exception as e:
                log.warning("드라이브 정리 실패: %s", e)

    lines = [f"{'✅' if ok else '⚠️'} 계정 {account} 업로드 ({row.number}행)"]
    for p, r in results.items():
        lines.append(f"• {PLATFORM_KO[p]}: {r}")
    if not ok:
        for h in dict.fromkeys(h for h in fix_hints if h):
            lines.append("\n" + h)
        lines.append(f"\n실패한 건 10분 간격으로 최대 {cfg.get('max_retries', 3)}번까지 자동 재시도합니다. 바로 다시 하려면 시트의 해당 결과 칸을 지우세요.")
    notify.send(cfg, "\n".join(lines))
    if results.get("tiktok", "").startswith("완료 초안") and text_for_tiktok:
        notify.send(cfg, f"📋 틱톡 본문 ({account}) — 길게 눌러 복사하세요")
        notify.send(cfg, text_for_tiktok)


def run_once(cfg) -> None:
    drive, sheets = owner_services()
    sheet = Sheet(sheets, cfg)
    for row in sheet.read():
        watchdog.beat()
        try:
            process_row(cfg, drive, sheet, row)
        except Exception:
            log.exception("%d행 처리 중 오류", row.number)
    for msg in youtube.flush_pending(cfg):
        notify.send(cfg, msg)


RESTARTS = int(os.environ.get("SNS_RESTARTS", "0"))
STATE = {"started": datetime.now(), "last_check": None, "last_error": None, "token_checked": None, "token_issues": []}
STATUS_ICON = {"완료": "✅", "일부실패": "⚠️", "처리중": "🔄", "": "⏳"}


def _ago(t: datetime) -> str:
    s = int((datetime.now() - t).total_seconds())
    if s < 60:
        return f"{s}초 전"
    if s < 3600:
        return f"{s // 60}분 전"
    return f"{s // 3600}시간 {s % 3600 // 60}분 전"


def status_text(cfg) -> str:
    up = datetime.now() - STATE["started"]
    lines = [
        "🤖 업로드 봇 상태",
        f"• PC: {HOST}",
        f"• 켜진 지: {up.days}일 {up.seconds // 3600}시간 {up.seconds % 3600 // 60}분" if up.days else f"• 켜진 지: {up.seconds // 3600}시간 {up.seconds % 3600 // 60}분",
        f"• 마지막 시트 확인: {_ago(STATE['last_check']) if STATE['last_check'] else '아직 없음'}",
    ]
    if RESTARTS:
        lines.append(f"• 자동 복구: {RESTARTS}번 다시 켜짐 (원인은 bot.log)")
    if STATE["last_error"]:
        lines.append(f"• 최근 오류: {STATE['last_error']}")
    if STATE["token_checked"]:
        lines.append(f"• 계정 연결: {'✅ 모두 정상' if not STATE['token_issues'] else '⚠️ 확인 필요'} ({_ago(STATE['token_checked'])} 점검)")
        lines += [f"    - {i}" for i in STATE["token_issues"]]
    pending_yt = len(youtube._load())
    if pending_yt:
        lines.append(f"• 유튜브 댓글 대기: {pending_yt}건 (공개로 바꾸면 자동)")

    _, sheets = owner_services()
    rows = Sheet(sheets, cfg).read()
    cols = cfg["sheet"]["columns"]
    counts = {"완료": 0, "일부실패": 0, "처리중": 0, "": 0}
    for r in rows:
        st = r.values.get(STATUS_COL, "").split("|")[0]
        counts[st if st in counts else ""] += 1
    lines.append(f"• 전체 {len(rows)}건: ✅완료 {counts['완료']} · ⚠️실패 {counts['일부실패']} · 🔄처리중 {counts['처리중']} · ⏳대기 {counts['']}")

    if rows:
        lines.append("\n최근 업로드")
        for r in rows[-5:][::-1]:
            st = r.values.get(STATUS_COL, "").split("|")[0]
            ts = r.values.get("타임스탬프", "")
            acct = r.values.get(cols["account"], "")
            title = (r.values.get(cols["yt_title"], "") or r.values.get(cols["body"], "")).strip().splitlines()
            title = title[0][:20] if title else ""
            lines.append(f"{STATUS_ICON.get(st, '⏳')} {r.number}행 {acct} · {title} ({ts.split(". ", 1)[-1].rsplit(":", 1)[0]})")
            if st == "일부실패":
                bad = [PLATFORM_KO[p] for p, c in RESULT_COLS.items() if r.values.get(c, "").startswith("실패")]
                lines.append(f"    실패: {', '.join(bad)}")
    return "\n".join(lines)


def daily_token_check(cfg) -> None:
    from sns.maintenance import check_tokens

    try:
        STATE["token_issues"] = check_tokens(cfg)
    except Exception as e:
        log.exception("토큰 점검 실패")
        STATE["token_issues"] = [f"점검 중 오류: {str(e)[:100]}"]
    STATE["token_checked"] = datetime.now()
    if STATE["token_issues"]:
        notify.send(cfg, "🔑 계정 연결 점검 — 확인이 필요해요\n" + "\n".join(f"• {i}" for i in STATE["token_issues"]))


def main() -> None:
    setup_logging()
    cfg = load_config()
    once = "--once" in sys.argv
    child = "--child" in sys.argv
    # 응답 없는 연결 때문에 영원히 멈추지 않도록 (개별 timeout 이 없는 곳 대비)
    socket.setdefaulttimeout(120)
    if not once and not child:
        from sns import single

        if not single.acquire():
            log.info("이미 실행 중이라 종료합니다")
            return
        # 감시자: 실제 봇을 따로 띄우고, 꺼지거나 멈추면 다시 켬
        watchdog.supervise(cfg, HOST)
        return
    if not once:
        from sns.telegram_bot import CommandListener, help_text

        watchdog.start(cfg, HOST)

        CommandListener(cfg, {"status": lambda: status_text(cfg), "help": help_text, "start": help_text}).start()
    log.info("업로드 봇 시작 (%s)", HOST)
    if not once:
        notify.send(cfg, f"🤖 업로드 봇 시작 ({HOST})\n상태 확인: /status")
    while True:
        watchdog.beat()
        if not once and (STATE["token_checked"] is None or datetime.now() - STATE["token_checked"] > timedelta(hours=24)):
            daily_token_check(cfg)
        try:
            run_once(cfg)
            STATE["last_check"] = datetime.now()
            STATE["last_error"] = None
        except Exception as e:
            log.exception("시트 확인 실패")
            STATE["last_error"] = f"{datetime.now():%H:%M} {str(e)[:150]}"
            notify.send(cfg, f"❗ 업로드 봇 오류: {str(e)[:300]}")
        if once:
            break
        time.sleep(cfg.get("poll_seconds", 60))


if __name__ == "__main__":
    main()
