"""Оркестрация одной новости: разбор текста → проверка дубля → медиа в
канал-хранилище → запись в news/news_media → карточка-ответ (см. 4.2–4.5 ТЗ)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from bot.config import config
from bot.services import ai, cards, media_storage, supabase_client
from bot.services.parse import Parsed, parse_by_entities, parse_by_lines, render_plain
from bot.services.slug import make_slug

logger = logging.getLogger(__name__)

MAX_MEDIA = 10


@dataclass
class Reply:
    text: str
    keyboard: InlineKeyboardMarkup | None = None


async def _parse_text(text: str, entities: list[dict]) -> Parsed:
    parsed = parse_by_entities(text, entities)
    if parsed and parsed.summary:
        return parsed

    if parsed:
        # Заголовок жирным есть, а курсивного описания нет — описание просим у AI,
        # заголовок и текст оставляем как в посте.
        data = await ai.split_news(text)
        if data and data.get("summary"):
            parsed.summary = data["summary"]
        else:
            parsed.warnings.append("описание (курсив) не найдено — проверь")
        return parsed

    data = await ai.split_news(render_plain(text, entities))
    if data:
        return Parsed(
            title=data["title"], summary=data["summary"], body=data["body"],
            warnings=["заголовок не выделен жирным — разобрал через AI, проверь"],
        )
    parsed = parse_by_lines(render_plain(text, entities))
    parsed.warnings.append("AI не ответил — взял первую строку как заголовок, вторую как описание, проверь")
    return parsed


def _collect_media(parts: list[dict[str, Any]], warnings: list[str]) -> tuple[list[dict], int]:
    items, skipped_big, other = [], 0, 0
    max_bytes = config.max_video_mb * 1024 * 1024
    for p in parts:
        if p.get("photo"):
            items.append({"kind": "photo", "file_id": p["photo"]["file_id"]})
        elif p.get("video"):
            size = p["video"].get("file_size") or 0
            if size > max_bytes:
                skipped_big += 1
            else:
                items.append({"kind": "video", "file_id": p["video"]["file_id"]})
        elif p.get("other"):
            other += 1
    if other:
        warnings.append("GIF/файлы/аудио не поддерживаются — не добавлены")
    if len(items) > MAX_MEDIA:
        warnings.append(f"медиа больше {MAX_MEDIA} — добавлены первые {MAX_MEDIA}")
        items = items[:MAX_MEDIA]
    return items, skipped_big


async def process_submission(bot: Bot, user_id: int, parts: list[dict[str, Any]]) -> Reply:
    parts = sorted(parts, key=lambda p: p["message_id"])
    with_text = next((p for p in parts if p.get("text")), None)
    if with_text is None:
        return Reply("✋ Нужен текст новости — перешли пост вместе с подписью.")

    origin_key = next((p["origin_key"] for p in parts if p.get("origin_key")), None)
    if origin_key:
        existing = await supabase_client.find_by_origin(origin_key)
        if existing:
            return _already(existing)

    parsed = await _parse_text(with_text["text"], with_text.get("entities") or [])
    warnings = list(parsed.warnings)
    items, skipped_big = _collect_media(parts, warnings)

    stored = await media_storage.copy_to_channel(bot, items)
    channel_ids = [s["channel_message_id"] for s in stored]

    try:
        row = await supabase_client.insert_news({
            "slug": make_slug(parsed.title),
            "title": parsed.title,
            "summary": parsed.summary,
            "body": parsed.body,
            "status": "published",
            "origin_key": origin_key,
            "telegram_user_id": user_id,
        })
    except supabase_client.DuplicateError:
        # Тот же пост одновременно прислали дважды — второй проиграл гонку.
        await media_storage.delete_from_channel(bot, channel_ids)
        existing = await supabase_client.find_by_origin(origin_key) if origin_key else None
        if existing:
            return _already(existing)
        raise
    except Exception:
        await media_storage.delete_from_channel(bot, channel_ids)
        raise

    try:
        await supabase_client.insert_media([
            {"news_id": row["id"], "position": i, **s} for i, s in enumerate(stored)
        ])
    except Exception:
        await supabase_client.delete_news(row["id"])
        await media_storage.delete_from_channel(bot, channel_ids)
        raise

    photos = sum(1 for s in stored if s["kind"] == "photo")
    videos = len(stored) - photos
    logger.info("Опубликована новость %s (%s фото, %s видео)", row["slug"], photos, videos)
    text = cards.published_card(
        parsed.title, parsed.summary, row["slug"], cards.media_note(photos, videos, skipped_big), warnings,
    )
    return Reply(text, cards.news_keyboard(row["id"], "published"))


def _already(existing: dict) -> Reply:
    note = " (сейчас скрыта)" if existing.get("status") == "hidden" else ""
    return Reply(
        f"ℹ️ Уже опубликовано{note}: {existing['title']}\n{cards.news_url(existing['slug'])}",
        cards.news_keyboard(existing["id"], existing.get("status") or "published"),
    )
