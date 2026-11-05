"""릴스 관리 웹 화면 ↔ 업로드 봇 연결 (명령 한 번 실행하고 끝나는 작은 프로그램).

웹 화면이 이걸 불러서 시트에 폼 응답과 같은 줄을 넣으면(영상 칸 = PC 경로, 텔레그램 /upload 와 같은 방식),
봇 본체가 평소처럼 처리한다 (재시도, /status, 결과 알림, 페북 자동 댓글 모두 그대로).

  python web_queue.py info    계정·다음 댓글 번호·봇 상태·PC 경로로 넣은 줄들의 진행 상황
  python web_queue.py add     (stdin JSON: account, video, title, body, comment) 시트에 한 줄 추가
  python web_queue.py retry   (stdin JSON: timestamp, video) 실패 칸을 지워 다시 올리게 함

결과는 stdout 에 JSON 한 줄. 실패하면 {"error": "..."} + 종료 코드 1.
줄은 (타임스탬프, 영상 경로)로 찾는다. 폼 응답이 들어오면 아래 줄이 밀려서 행 번호는 바뀔 수 있다.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from run import fail_count
from sns.config import PLATFORM_KO, load_config, redact
from sns.google_client import is_local_path, owner_services
from sns.sheet import RESULT_COLS, STATUS_COL, Sheet
from sns.single import PID_FILE, pid_alive
from sns.tg_upload import form_timestamp

# 폼의 플랫폼 체크박스 문구와 같아야 함. 페북은 disabled_platforms 라서 봇이 올리지 않고,
# 직접 올리면 fb_comments 가 이 줄의 댓글 번호로 댓글만 단다 (폼으로 낼 때와 같음)
PLATFORM_TEXT = "인스타, 쓰레드, 유튜브, 페이스북"


def _sheet(cfg: dict) -> Sheet:
    _, sheets = owner_services()
    return Sheet(sheets, cfg)


def bot_running() -> bool:
    try:
        return pid_alive(int(PID_FILE.read_text().strip()))
    except (OSError, ValueError):
        return False


def row_state(cfg: dict, v: dict) -> str:
    """waiting 대기 / running 올리는 중 / retrying 자동 재시도 남음 / failed 재시도 끝 / done / blocked."""
    status = v.get(STATUS_COL, "").split("|")[0]
    if status == "완료":
        return "done"
    if status == "차단":
        return "blocked"
    if status == "처리중":
        return "running"
    if status == "일부실패":
        cells = [v.get(c, "") for c in RESULT_COLS.values()]
        bad = [c for c in cells if c.startswith("실패")]
        give_up = bad and all(fail_count(c) >= cfg.get("max_retries", 3) for c in bad)
        return "failed" if give_up else "retrying"
    return "waiting"


def next_comment(cfg: dict, rows: list) -> dict:
    """계정별 다음 링크 번호 (지금까지 쓴 가장 큰 번호 + 1). 제안일 뿐이라 화면에서 고칠 수 있다."""
    cols = cfg["sheet"]["columns"]
    labels = cfg.get("account_labels") or {}
    top = {name: 0 for name in labels}
    for r in rows:
        acct = r.values.get(cols["account"], "").strip()
        raw = r.values.get(cols.get("comment", "댓글"), "").strip()
        if acct in top and raw.isdigit():
            top[acct] = max(top[acct], int(raw))
    return {name: n + 1 for name, n in top.items()}


def info(cfg: dict, _req: dict) -> dict:
    rows = _sheet(cfg).read()
    cols = cfg["sheet"]["columns"]
    local = []
    for r in rows:
        video = r.values.get(cols["video"], "")
        if not is_local_path(video):
            continue
        local.append({
            "timestamp": r.values.get("타임스탬프", ""),
            "video": video.strip(),
            "state": row_state(cfg, r.values),
            "results": {PLATFORM_KO[p]: r.values[c] for p, c in RESULT_COLS.items() if r.values.get(c)},
        })
    yt = cfg.get("youtube") or {}
    return {
        "accounts": list((cfg.get("account_labels") or {}).keys()),
        "next_comment": next_comment(cfg, rows),
        "bot_running": bot_running(),
        "comment_template": cfg.get("comment_template") or "",
        "instagram_comment": cfg.get("instagram_comment") or "",
        "youtube_privacy": yt.get("privacy", "private"),
        "youtube_comment_wait": yt.get("comment_wait_minutes", 20),
        "rows": local,
    }


def add(cfg: dict, req: dict) -> dict:
    account = (req.get("account") or "").strip()
    video = (req.get("video") or "").strip()
    title = (req.get("title") or "").strip()
    body = (req.get("body") or "").strip()
    if account not in (cfg.get("account_labels") or {}):
        raise ValueError(f"알 수 없는 계정이에요: {account}")
    if not is_local_path(video) or not Path(video).is_file():
        raise ValueError(f"영상 파일을 찾을 수 없어요: {video}")
    if not title or not body:
        raise ValueError("유튜브 제목과 본문이 필요해요")
    cols = cfg["sheet"]["columns"]
    stamp = form_timestamp(datetime.now())
    _sheet(cfg).append({
        "타임스탬프": stamp,
        cols["account"]: account,
        cols["video"]: video,
        cols["yt_title"]: title,
        cols["body"]: body,
        cols["tiktok_body"]: "",
        cols["platforms"]: PLATFORM_TEXT,
        cols.get("comment", "댓글"): (req.get("comment") or "").strip(),
    })
    return {"timestamp": stamp, "video": video}


def retry(cfg: dict, req: dict) -> dict:
    sheet = _sheet(cfg)
    video_col = cfg["sheet"]["columns"]["video"]
    for r in sheet.read():
        if r.values.get("타임스탬프", "") == req.get("timestamp") and r.values.get(video_col, "").strip() == req.get("video"):
            cleared = [c for c in RESULT_COLS.values() if r.values.get(c, "").startswith("실패")]
            for c in cleared:
                sheet.write(r, c, "")
            sheet.write(r, STATUS_COL, "")
            return {"cleared": len(cleared)}
    raise ValueError("시트에서 그 줄을 찾지 못했어요")


COMMANDS = {"info": info, "add": add, "retry": retry}


def main() -> int:
    out = sys.stdout.buffer
    try:
        cmd = sys.argv[1] if len(sys.argv) > 1 else ""
        if cmd not in COMMANDS:
            raise ValueError(f"알 수 없는 명령: {cmd}")
        raw = sys.stdin.buffer.read().decode("utf-8") if cmd != "info" else ""
        result = COMMANDS[cmd](load_config(), json.loads(raw) if raw.strip() else {})
        code = 0
    except Exception as e:  # noqa: BLE001  (웹 화면이 그대로 보여 줄 수 있게 글자로 돌려줌)
        result = {"error": redact(str(e))[:500]}
        code = 1
    out.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    out.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
