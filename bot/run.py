"""업로드 봇 본체.

  python run.py          계속 실행 (시트를 주기적으로 확인)
  python run.py --once   한 번만 확인하고 종료
"""
import logging
import re
import socket
import sys
import time
from datetime import datetime, timedelta

from sns import captions, notify
from sns.config import PLATFORM_KO, PLATFORMS, TMP_DIR, load_config, setup_logging
from sns.google_client import download, file_id_from_url, owner_services
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


def is_locked(status: str) -> bool:
    if not status.startswith("처리중"):
        return False
    try:
        ts = datetime.fromisoformat(status.split("|")[2])
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
    results = {}
    try:
        file_id = file_id_from_url(v[cols["video"]].split(",")[0])
        path = download(drive, file_id, TMP_DIR)
        text = captions.build(
            cfg,
            v.get(cols["yt_title"], ""),
            v.get(cols["body"], ""),
            v.get(cols["tiktok_body"], ""),
            todo,
        )
        for p in todo:
            try:
                if p == "youtube":
                    res = youtube.upload(cfg, account, path, text["youtube"])
                elif p == "instagram":
                    res = meta.upload_instagram(cfg, account, path, text["instagram"])
                elif p == "facebook":
                    res = meta.upload_facebook(cfg, account, path, text["facebook"])
                elif p == "threads":
                    res = threads.upload(cfg, account, drive, file_id, text["threads"])
                else:
                    res = tiktok.upload(cfg, account, path, text["tiktok"])
                cell = f"완료 {res}"
            except Exception as e:
                log.exception("%s 업로드 실패", p)
                prev = fail_count(row.values.get(RESULT_COLS[p], ""))
                cell = f"실패{prev + 1}: {str(e)[:300]}"
            results[p] = cell
            sheet.write(row, RESULT_COLS[p], cell)
    except Exception as e:
        log.exception("%d행 준비 실패", row.number)
        for p in todo:
            prev = fail_count(row.values.get(RESULT_COLS[p], ""))
            results[p] = f"실패{prev + 1}: {str(e)[:300]}"
            sheet.write(row, RESULT_COLS[p], results[p])
    finally:
        if path and path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    ok = all(r.startswith("완료") for r in results.values())
    now = datetime.now().isoformat(timespec="seconds")
    sheet.write(row, STATUS_COL, "완료" if ok else f"일부실패|{now}")

    lines = [f"{'✅' if ok else '⚠️'} 계정 {account} 업로드 ({row.number}행)"]
    for p, r in results.items():
        lines.append(f"• {PLATFORM_KO[p]}: {r}")
    if not ok:
        lines.append(f"\n실패한 건 10분 간격으로 최대 {cfg.get('max_retries', 3)}번까지 자동 재시도합니다. 바로 다시 하려면 시트의 해당 결과 칸을 지우세요.")
    notify.send(cfg, "\n".join(lines))


def run_once(cfg) -> None:
    drive, sheets = owner_services()
    sheet = Sheet(sheets, cfg)
    for row in sheet.read():
        try:
            process_row(cfg, drive, sheet, row)
        except Exception:
            log.exception("%d행 처리 중 오류", row.number)


def main() -> None:
    setup_logging()
    cfg = load_config()
    once = "--once" in sys.argv
    log.info("업로드 봇 시작 (%s)", HOST)
    if not once:
        notify.send(cfg, f"🤖 업로드 봇 시작 ({HOST})")
    while True:
        try:
            run_once(cfg)
        except Exception as e:
            log.exception("시트 확인 실패")
            notify.send(cfg, f"❗ 업로드 봇 오류: {str(e)[:300]}")
        if once:
            break
        time.sleep(cfg.get("poll_seconds", 60))


if __name__ == "__main__":
    main()
