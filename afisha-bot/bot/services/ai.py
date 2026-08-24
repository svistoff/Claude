"""Извлечение структурированных полей события из текста анонса через OpenAI.

Модель обязана вернуть только JSON (без markdown-обёрток и преамбулы) — но
markdown-обёртки всё равно защитно срезаются: этот баг уже ловили в repost-bot.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI

from bot.config import config

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

_WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

_FIELDS = (
    "title", "performer", "short_description", "full_description", "price",
    "external_url", "venue_name", "schedule_type", "starts_on", "ends_on",
    "start_time", "end_time", "weekdays", "date_confidence",
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.openai_api_key)
    return _client


def _now_in_ekb() -> datetime:
    return datetime.now(timezone(timedelta(hours=config.tz_offset_hours)))


def _system_prompt() -> str:
    now = _now_in_ekb()
    weekday = _WEEKDAYS_RU[now.weekday()]
    return f"""Сегодня {now:%d.%m.%Y} ({weekday}), время в Екатеринбурге (UTC+5). Ты обрабатываешь
пересланный анонс мероприятия из Telegram-канала и извлекаешь из него структурированные
данные для афиши. Верни ТОЛЬКО JSON-объект (без markdown-обёрток, без пояснений вне JSON)
со следующими полями:

- title: string — заголовок события, ≤80 символов
- performer: string|null — артист/диджей/хедлайнер, если есть
- short_description: string — 1-2 предложения для карточки
- full_description: string — полный текст анонса
- price: string|null — цена текстом ('от 500 ₽', 'бесплатно')
- external_url: string|null — ссылка на билеты, если в тексте есть
- venue_name: string|null — название площадки текстом
- schedule_type: "single"|"range"|"weekly"|null
- starts_on: "YYYY-MM-DD"|null
- ends_on: "YYYY-MM-DD"|null — для single равно starts_on
- start_time: "HH:MM"|null
- end_time: "HH:MM"|null
- weekdays: [int]|null — ISO 1=Пн...7=Вс, только для schedule_type=weekly
- date_confidence: "high"|"low"

Правила разбора дат:
- Указан один день → schedule_type="single", starts_on=ends_on.
- Диапазон дат ("с 5 по 8 сентября", фестиваль) → schedule_type="range".
- Повтор по дням недели ("каждую субботу", "по пятницам") → schedule_type="weekly",
  заполни weekdays и, если указаны, границы starts_on/ends_on.
- Относительные даты ("завтра", "в пятницу", "в эти выходные") разрешай относительно
  сегодняшней даты и часового пояса Екатеринбурга, указанных выше.
- Неизвестное поле — null, не выдумывай значения.
- date_confidence="low", если дата не указана явно и её пришлось предполагать, иначе "high".
- title не должен быть пустым: если явного заголовка нет, сформулируй его по смыслу анонса."""


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw.strip()).strip()


def empty_fields() -> dict:
    return {field: None for field in _FIELDS} | {"parse_failed": False}


def _fallback_fields(text: str) -> dict:
    fields = empty_fields()
    fields["full_description"] = text
    fields["parse_failed"] = True
    return fields


def _normalize(data: dict) -> dict:
    fields = empty_fields()
    for key in _FIELDS:
        if key in data:
            fields[key] = data[key]
    if fields["schedule_type"] == "single" and fields["starts_on"] and not fields["ends_on"]:
        fields["ends_on"] = fields["starts_on"]
    if not fields["date_confidence"]:
        fields["date_confidence"] = "high" if fields["starts_on"] else "low"
    return fields


async def extract_fields(text: str) -> dict:
    """Возвращает распознанные поля события. При любой ошибке — не теряет анонс,
    а возвращает fallback с исходным текстом в full_description (см. 3.2 ТЗ)."""
    client = _get_client()
    try:
        response = await client.chat.completions.create(
            model=config.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": text},
            ],
        )
        raw = response.choices[0].message.content or ""
    except Exception:
        logger.exception("Ошибка запроса к OpenAI при разборе анонса")
        return _fallback_fields(text)

    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("ответ AI — не JSON-объект")
    except (json.JSONDecodeError, ValueError):
        logger.warning("Не удалось распарсить JSON от AI: %r", raw)
        return _fallback_fields(text)

    return _normalize(data)
