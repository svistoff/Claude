"""Разбор фото/видео вложений: выбор обложки, проверка лимита видео 20 МБ."""
from __future__ import annotations

from bot.config import config


def is_video_too_large(file_size: int | None) -> bool:
    """Жёсткий лимит на видео (см. 3.3/4.7 ТЗ). Если размер неизвестен — не блокируем:
    Telegram всегда присылает file_size для видео, это защитный случай."""
    if file_size is None:
        return False
    return file_size > config.max_video_mb * 1024 * 1024
