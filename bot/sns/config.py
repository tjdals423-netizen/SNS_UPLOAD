"""설정(config.yaml)과 토큰 저장소(secrets/tokens.json) 관리."""
import json
import logging
import os
from pathlib import Path

import yaml

BOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BOT_DIR / "config.yaml"
SECRETS_DIR = BOT_DIR / "secrets"
TOKENS_PATH = SECRETS_DIR / "tokens.json"
GOOGLE_CLIENT_PATH = SECRETS_DIR / "google_client.json"
TMP_DIR = BOT_DIR / "tmp"
LOG_DIR = BOT_DIR / "logs"

PLATFORMS = ["youtube", "instagram", "facebook", "threads", "tiktok"]
PLATFORM_KO = {
    "youtube": "유튜브",
    "instagram": "인스타",
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


def update_token(section: str, key: str, value) -> None:
    tokens = load_tokens()
    tokens.setdefault(section, {})[key] = value
    save_tokens(tokens)


def setup_logging() -> None:
    import sys

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")]
    if sys.stderr is not None:  # 백그라운드(pythonw) 실행이면 화면 출력 없음
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=handlers)
