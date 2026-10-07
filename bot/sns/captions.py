"""플랫폼별 글 만들기.

- 유튜브: 제목만 (설명란 비움)
- 인스타 / 쓰레드 / 페북: 공통 본문
- 틱톡: 틱톡 전용 본문
빈 칸은 AI(키가 있을 때) 또는 간단한 규칙으로 채움.
"""
import json
import logging
import os
import re

log = logging.getLogger(__name__)

YT_TITLE_MAX = 100
THREADS_MAX = 500
CAPTION_MAX = 2200


def _first_line(text: str, limit: int) -> str:
    line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    line = re.sub(r"#\S+", "", line).strip() or line
    return line[:limit]


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ai(cfg: dict, prompt: str) -> dict | None:
    key = (cfg.get("ai") or {}).get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        resp = client.beta.messages.create(
            model=(cfg.get("ai") or {}).get("model", "claude-opus-5-5"),
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            log.warning("AI 가 캡션 작성을 거절함")
            return None
        text = "".join(b.text for b in resp.content if b.type == "text")
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # AI 실패해도 업로드는 계속
        log.warning("AI 캡션 생성 실패: %s", e)
        return None


def build(cfg: dict, title: str, body: str, tiktok_body: str, platforms: list[str]) -> dict:
    title, body, tiktok_body = title.strip(), body.strip(), tiktok_body.strip()
    need_title = "youtube" in platforms and not title
    need_body = any(p in platforms for p in ("instagram", "threads", "facebook")) and not body
    need_tt = "tiktok" in platforms and not tiktok_body
    shorten_threads = "threads" in platforms and len(body) > THREADS_MAX

    if need_title or need_body or need_tt or shorten_threads:
        prompt = (
            "한국어 숏폼 영상 크리에이터의 SNS 업로드 글을 채워줘. 이미 있는 글의 말투와 내용을 그대로 따라가고, "
            "없는 정보는 지어내지 마.\n\n"
            f"[유튜브 제목]\n{title or '(비어 있음)'}\n\n"
            f"[공통 본문 - 인스타/쓰레드/페북]\n{body or '(비어 있음)'}\n\n"
            f"[틱톡 본문]\n{tiktok_body or '(비어 있음)'}\n\n"
            "다음 JSON 하나만 출력해. 이미 채워진 칸은 그대로 복사해.\n"
            '{"youtube_title": "100자 이하, 해시태그 없이", '
            '"body": "공통 본문", "tiktok_body": "틱톡 본문", '
            '"threads_body": "공통 본문을 500자 이하로 다듬은 것"}'
        )
        ai = _ai(cfg, prompt) or {}
        if need_title:
            title = (ai.get("youtube_title") or "").strip()
        if need_body:
            body = (ai.get("body") or "").strip()
        if need_tt:
            tiktok_body = (ai.get("tiktok_body") or "").strip()
        threads_body = (ai.get("threads_body") or "").strip() if shorten_threads else ""
    else:
        threads_body = ""

    # AI 없이도 동작하도록 규칙 기반 대체
    if not body:
        body = tiktok_body or title
    if not tiktok_body:
        tiktok_body = body or title
    if not title:
        title = _first_line(body or tiktok_body, YT_TITLE_MAX)
    title = title.replace("<", "").replace(">", "")[:YT_TITLE_MAX]
    threads_body = threads_body if threads_body and len(threads_body) <= THREADS_MAX else _cut(body, THREADS_MAX)

    return {
        "youtube": title,
        "instagram": _cut(body, CAPTION_MAX),
        "facebook": body,
        "threads": threads_body,
        "tiktok": _cut(tiktok_body, CAPTION_MAX),
    }
