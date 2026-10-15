"""Оркестрация одной заявки: AI-разбор → медиа → запись в event_submissions →
карточка-ответ пользователю (см. 3.2-3.5 ТЗ)."""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from aiogram import Bot

from bot.config import config
from bot.services import ai, media, supabase_client, video_storage

logger = logging.getLogger(__name__)

_MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
_WEEKDAYS_SHORT_RU = ["", "пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _day_str(iso_date: str | None) -> str:
    if not iso_date:
        return ""
    parts = iso_date.split("-")
    if len(parts) != 3:
        return iso_date
    return f"{int(parts[2])} {_MONTHS_RU[int(parts[1])]}"


def _human_when(fields: dict) -> str:
    if not fields.get("starts_on"):
        return "не распознано"
    t = (fields.get("start_time") or "")[:5]
    schedule_type = fields.get("schedule_type") or "single"
    if schedule_type == "range" and fields.get("ends_on"):
        base = f"{_day_str(fields['starts_on'])} – {_day_str(fields['ends_on'])}"
    elif schedule_type == "weekly":
        days = ", ".join(_WEEKDAYS_SHORT_RU[w] for w in (fields.get("weekdays") or []) if 0 < w < 8)
        base = f"по {days}" if days else "еженедельно"
    else:
        base = _day_str(fields["starts_on"])
    return f"{base}, {t}" if t else base


def _format_reply(fields: dict, media_note: str, warnings: list[str]) -> str:
    lines = [
        "✅ Заявка в «Предложенное»",
        f"Заголовок: {fields['title']}",
        f"Когда: {_human_when(fields)}",
        f"Площадка: {fields.get('venue_name') or '—'}",
        f"Медиа: {media_note}",
        f"Проверь и опубликуй: {config.admin_url}",
    ]
    if warnings:
        lines.append("")
        lines.extend(f"⚠️ {w}" for w in warnings)
    return "\n".join(lines)


async def process_submission(bot: Bot, user_id: int, parts: list[dict[str, Any]]) -> str:
    text = next((p["text"] for p in parts if p["text"]), None)
    photo = next((p["photo"] for p in parts if p["photo"]), None)
    video = next((p["video"] for p in parts if p["video"]), None)

    warnings: list[str] = []

    fields = await ai.extract_fields(text) if text else ai.empty_fields()
    if fields.get("parse_failed"):
        warnings.append("AI не смог распознать структуру — проверь вручную")
    if not fields.get("title"):
        fields["title"] = (text.splitlines()[0][:80] if text else "Без названия")
    # дата из анонса, как есть (может быть None) — по ней чистится видео-хранилище;
    # подставленная ниже «сегодня» для этого не годится
    real_event_date = fields.get("ends_on") or fields.get("starts_on")
    if not fields.get("starts_on"):
        # в event_submissions расписание обязательно (NOT NULL), а в анонсе даты
        # может не быть — ставим сегодняшнюю, модератор поправит в админке
        today = ai._now_in_ekb().date()
        if fields.get("schedule_type") == "weekly" and fields.get("weekdays"):
            fields["starts_on"] = today.isoformat()
            fields["ends_on"] = fields.get("ends_on") or (today + timedelta(days=90)).isoformat()
            warnings.append("у повтора по дням нет дат — поставил с сегодня на 3 месяца, проверь в афише")
        else:
            fields["schedule_type"] = "single"
            fields["starts_on"] = fields["ends_on"] = today.isoformat()
            fields["weekdays"] = None
            warnings.append("даты в анонсе нет — поставил сегодняшнюю, исправь в афише перед публикацией")
    elif fields.get("date_confidence") == "low":
        warnings.append("дату распознал неуверенно — проверь в афише")
    if not fields.get("ends_on"):
        fields["ends_on"] = fields["starts_on"]
    if not fields.get("schedule_type"):
        fields["schedule_type"] = "single" if fields["ends_on"] == fields["starts_on"] else "range"

    cover_url = None
    if photo:
        buf = await bot.download(photo["file_id"])
        cover_url, _ = await supabase_client.upload_file(
            # уникальное имя: тот же пост можно переслать повторно (file_id тот же),
            # а Storage на совпадающий путь отвечает 409 Duplicate
            "event-posters", f"submissions/{uuid.uuid4().hex}.jpg", buf.read(), "image/jpeg",
        )

    media_parts = []
    if cover_url:
        media_parts.append("фото ✓")

    video_url = None
    if video:
        if media.is_video_too_large(video["file_size"]):
            warnings.append("видео >20 МБ — не добавлено, залей вручную")
        else:
            video_url = await video_storage.store_video(bot, video["file_id"], real_event_date, user_id)
            media_parts.append("видео ✓")

    payload = {
        "title": fields["title"],
        "performer": fields.get("performer"),
        "short_description": fields.get("short_description"),
        "full_description": fields.get("full_description") or text or "",
        "price": fields.get("price"),
        "external_url": fields.get("external_url"),
        "venue_name": fields.get("venue_name"),
        "schedule_type": fields.get("schedule_type"),
        "starts_on": fields.get("starts_on"),
        "ends_on": fields.get("ends_on"),
        "start_time": fields.get("start_time"),
        "weekdays": fields.get("weekdays"),
        "cover_image_url": cover_url,
        "video_url": video_url,
        "status": "pending",
        "submitter_name": "afisha-bot",
    }
    await supabase_client.insert_event_submission(payload)

    media_note = ", ".join(media_parts) if media_parts else "нет"
    return _format_reply(fields, media_note, warnings)
