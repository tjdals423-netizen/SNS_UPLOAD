"""텔레그램 /upload: PC 폴더의 완성본.mp4 + 캡션.txt 를 업로드 대기열(시트)에 넣기.

순서: 계정 버튼 → 폴더 경로 → 유튜브 제목 → 댓글 번호 → [업로드] 확인
시트에 폼 응답과 같은 형식으로 한 줄을 추가하면, 봇 본체가 평소처럼 처리한다
(재시도, /status, 결과 알림, 페북 자동 댓글 모두 그대로).
"""
import logging
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO_NAME = "완성본.mp4"
CAPTION_NAME = "캡션.txt"
PLATFORM_TEXT = "인스타, 쓰레드, 유튜브"  # 폼의 플랫폼 체크박스 문구와 같아야 함
TIMEOUT = 15 * 60  # 15분 동안 입력이 없으면 취소


def form_timestamp(t: datetime) -> str:
    """구글 폼과 같은 타임스탬프 형식: '2026. 10. 15 오후 1:51:30'."""
    ap = "오전" if t.hour < 12 else "오후"
    h = t.hour % 12 or 12
    return f"{t.year}. {t.month}. {t.day} {ap} {h}:{t.minute:02d}:{t.second:02d}"


def kb(rows):
    """인라인 버튼. rows = [[(글자, data), ...], ...]"""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


class UploadConversation:
    def __init__(self, cfg: dict, append_row):
        self.cfg = cfg
        self.append_row = append_row  # dict(열 제목 → 값) 을 시트에 추가하는 함수
        self.reset()

    def reset(self):
        self.step, self.data, self.touched = None, {}, 0.0

    @property
    def active(self) -> bool:
        if self.step and time.time() - self.touched > TIMEOUT:
            self.reset()
        return self.step is not None

    def _accounts(self):
        return list(dict.fromkeys((self.cfg.get("account_labels") or {}).keys()))

    # ── 시작 ──
    def start(self):
        self.reset()
        self.step, self.touched = "account", time.time()
        accts = self._accounts()
        rows = [[(a, f"up:acct:{a}") for a in accts[i:i + 2]] for i in range(0, len(accts), 2)]
        rows.append([("❌ 취소", "up:cancel")])
        return [("📤 어느 계정에 올릴까요?", kb(rows))]

    def cancel(self):
        was = self.step is not None
        self.reset()
        return [("취소했어요." if was else "진행 중인 업로드가 없어요.", None)]

    # ── 버튼 ──
    def on_callback(self, data: str):
        self.touched = time.time()
        if data == "up:cancel":
            return self.cancel()
        if data.startswith("up:acct:") and self.step == "account":
            acct = data.split(":", 2)[2]
            if acct not in self._accounts():
                return [("알 수 없는 계정이에요. /upload 로 다시 시작해 주세요.", None)]
            self.data["account"] = acct
            self.step = "path"
            return [(f"✅ 계정: {acct}\n\n📁 폴더 경로를 보내주세요.\n예: C:\\auto_create_reels\\output\\001_초코_바나나_견과류_머핀", None)]
        if data == "up:go" and self.step == "confirm":
            return self._submit()
        return [("지금은 그 버튼을 쓸 수 없어요. /upload 로 다시 시작해 주세요.", None)]

    # ── 글자 입력 ──
    def on_text(self, text: str):
        self.touched = time.time()
        text = text.strip()
        if self.step == "path":
            folder = Path(text.strip().strip('"').strip("'"))
            video, caption = folder / VIDEO_NAME, folder / CAPTION_NAME
            missing = [n for n, f in ((VIDEO_NAME, video), (CAPTION_NAME, caption)) if not f.is_file()]
            if not folder.is_dir():
                return [(f"❗ 폴더를 찾을 수 없어요: {folder}\n경로를 다시 보내주세요. (그만하려면 /cancel)", None)]
            if missing:
                return [(f"❗ 폴더에 {', '.join(missing)} 이(가) 없어요.\n다른 경로를 보내주세요. (그만하려면 /cancel)", None)]
            body = caption.read_text(encoding="utf-8-sig").strip()
            if not body:
                return [("❗ 캡션.txt 가 비어 있어요. 캡션을 채운 뒤 경로를 다시 보내주세요.", None)]
            size_mb = video.stat().st_size / 1024 / 1024
            self.data.update(folder=folder, video=video, body=body)
            self.step = "title"
            preview = body if len(body) <= 300 else body[:300] + "…"
            return [
                (f"✅ 영상: {VIDEO_NAME} ({size_mb:.0f}MB)\n\n📝 캡션 미리보기\n{preview}", None),
                ("🎬 유튜브 제목을 보내주세요. (100자 이내)", None),
            ]
        if self.step == "title":
            if not text:
                return [("유튜브 제목을 보내주세요.", None)]
            if len(text) > 100:
                return [(f"❗ 제목이 {len(text)}자예요. 100자 이내로 다시 보내주세요.", None)]
            self.data["title"] = text.replace("<", "").replace(">", "")
            self.step = "comment"
            return [("🔢 댓글 링크 번호를 보내주세요. (유튜브·페북·쓰레드 댓글용, 없으면 0)", None)]
        if self.step == "comment":
            num = "" if text in ("0", "없음", "-") else text
            self.data["comment"] = num
            self.step = "confirm"
            d = self.data
            summary = (
                "📋 이렇게 올릴게요\n"
                f"• 계정: {d['account']}\n"
                f"• 폴더: {d['folder'].name}\n"
                f"• 유튜브 제목: {d['title']}\n"
                f"• 댓글 번호: {num or '없음'}\n"
                f"• 올릴 곳: 유튜브 · 인스타 · 쓰레드 (페북은 직접 올리면 댓글 자동)"
            )
            return [(summary, kb([[("✅ 업로드", "up:go"), ("❌ 취소", "up:cancel")]]))]
        return [("버튼을 눌러 주세요. 처음부터 하려면 /upload, 그만하려면 /cancel", None)]

    # ── 시트에 추가 ──
    def _submit(self):
        d = self.data
        cols = self.cfg["sheet"]["columns"]
        values = {
            "타임스탬프": form_timestamp(datetime.now()),
            cols["account"]: d["account"],
            cols["video"]: str(d["video"]),
            cols["yt_title"]: d["title"],
            cols["body"]: d["body"],
            cols["tiktok_body"]: "",
            cols["platforms"]: PLATFORM_TEXT,
            cols.get("comment", "댓글"): d["comment"],
        }
        try:
            self.append_row(values)
        except Exception as e:
            log.exception("업로드 대기열 추가 실패")
            return [(f"❗ 대기열에 넣지 못했어요: {str(e)[:200]}\n다시 시도하려면 ✅ 업로드를 한 번 더 눌러 주세요.", None)]
        acct = d["account"]
        self.reset()
        return [(f"🚀 {acct} 업로드 대기열에 넣었어요. 1분 안에 시작하고, 끝나면 결과 알림이 와요.", None)]
