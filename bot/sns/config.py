"""설정(config.yaml)과 토큰 저장소(secrets/tokens.json) 관리."""
import json
import logging
import os
import re
import threading
from pathlib import Path

import yaml

BOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BOT_DIR / "config.yaml"
SECRETS_DIR = BOT_DIR / "secrets"
TOKENS_PATH = SECRETS_DIR / "tokens.json"
GOOGLE_CLIENT_PATH = SECRETS_DIR / "google_client.json"
TMP_DIR = BOT_DIR / "tmp"
LOG_DIR = BOT_DIR / "logs"

# instagram_story: 폼 체크박스가 아니라 인스타 릴스를 새로 올릴 때 같이 (사용자 지정 2026-11-10, config instagram_story)
PLATFORMS = ["youtube", "instagram", "instagram_story", "facebook", "threads", "tiktok"]
PLATFORM_KO = {
    "youtube": "유튜브",
    "instagram": "인스타",
    "instagram_story": "인스타스토리",
    "facebook": "페북",
    "threads": "쓰레드",
    "tiktok": "틱톡",
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"config.yaml 이 없습니다. config.example.yaml 을 복사해서 {CONFIG_PATH} 로 만들어 주세요."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_tokens() -> dict:
    if not TOKENS_PATH.exists():
        return {}
    with open(TOKENS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_tokens(tokens: dict) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TOKENS_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TOKENS_PATH)


_TOKEN_LOCK = threading.Lock()  # 여러 행을 동시에 올릴 때 토큰 파일을 서로 덮어쓰지 않게


def update_token(section: str, key: str, value) -> None:
    with _TOKEN_LOCK:
        tokens = load_tokens()
        tokens.setdefault(section, {})[key] = value
        save_tokens(tokens)


SECRET_PATTERNS = [
    (re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"), "bot***"),  # 텔레그램 봇 토큰 (요청 주소에 들어감)
    (re.compile(r"(access_token=)[^&\s'\"]+"), r"\1***"),
]


def redact(text: str) -> str:
    for pat, rep in SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return text


class _RedactFormatter(logging.Formatter):
    """오류 메시지에 섞여 들어온 토큰을 로그에 남기지 않음."""

    def format(self, record):
        return redact(super().format(record))


def setup_logging() -> None:
    import sys

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")]
    if sys.stderr is not None:  # 백그라운드(pythonw) 실행이면 화면 출력 없음
        handlers.append(logging.StreamHandler())
    fmt = _RedactFormatter("%(asctime)s [%(levelname)s] %(message)s")
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
