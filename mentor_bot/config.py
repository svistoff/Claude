"""Настройки из .env (без сторонних зависимостей)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    """Подхватить KEY=VALUE из .env. Уже заданные переменные окружения не трогаем."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Config:
    bot_token: str
    owner_chat_id: int  # 0 = ещё не задан (режим настройки)
    llm_api_key: str
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    stt_api_key: str = ""
    stt_base_url: str = "https://api.groq.com/openai/v1"
    stt_model: str = "whisper-large-v3-turbo"
    tz_offset_hours: int = 5
    plan_time: str = "08:30"
    default_time: str = "09:00"
    evening_time: str = "20:00"
    db_path: str = "data/mentor.db"


def load() -> Config:
    load_env_file(ROOT_DIR / ".env")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    owner = os.environ.get("OWNER_CHAT_ID", "")
    if not token:
        raise SystemExit("Задай TELEGRAM_BOT_TOKEN в .env")
    # OWNER_CHAT_ID пустой = режим настройки: бот отвечает любому его chat_id.
    db_path = os.environ.get("DB_PATH", "data/mentor.db")
    if not Path(db_path).is_absolute():
        db_path = str(ROOT_DIR / db_path)
    return Config(
        bot_token=token,
        owner_chat_id=int(owner) if owner else 0,
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        llm_model=os.environ.get("LLM_MODEL", "deepseek-flash"),
        stt_api_key=os.environ.get("STT_API_KEY", ""),
        stt_base_url=os.environ.get("STT_BASE_URL", "https://api.groq.com/openai/v1"),
        stt_model=os.environ.get("STT_MODEL", "whisper-large-v3-turbo"),
        tz_offset_hours=int(os.environ.get("TZ_OFFSET_HOURS", "5")),
        plan_time=os.environ.get("PLAN_TIME", "08:30"),
        default_time=os.environ.get("DEFAULT_TIME", "09:00"),
        evening_time=os.environ.get("EVENING_TIME", "20:00"),
        db_path=db_path,
    )
