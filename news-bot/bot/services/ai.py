"""Запасной разбор новости через OpenAI — когда в посте нет жирного заголовка
или нет курсивного описания (см. 4.2 ТЗ).

Модель обязана вернуть только JSON, но markdown-обёртки всё равно защитно
срезаются — этот баг уже ловили в repost-bot.
"""
from __future__ import annotations

import json
import logging
import re

from openai import AsyncOpenAI

from bot.config import config

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

_SYSTEM_PROMPT = """Ты помогаешь редактору городского новостного сайта Екатеринбурга.
Тебе присылают текст новости из Telegram. Раздели его на части и верни ТОЛЬКО
JSON-объект (без markdown-обёрток и пояснений) с полями:

- title: string — заголовок новости, не длиннее 110 символов
- summary: string — одно предложение, суть новости, не длиннее 200 символов
- body: string — полный текст новости без заголовка, абзацы через пустую строку

Правила:
- Ничего не выдумывай и не меняй факты, цифры, имена, даты.
- Если в тексте уже есть заголовок (первая строка) — возьми его, не переписывай.
- body — исходный текст как есть (без заголовка), хэштеги и ссылки в конце оставь.
- Пиши по-русски."""


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.openai_api_key)
    return _client


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw.strip()).strip()


async def split_news(text: str) -> dict | None:
    """{'title','summary','body'} или None, если AI не ответил / вернул не то."""
    try:
        response = await _get_client().chat.completions.create(
            model=config.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        raw = response.choices[0].message.content or ""
    except Exception:
        logger.exception("Ошибка запроса к OpenAI при разборе новости")
        return None

    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Не удалось распарсить JSON от AI: %r", raw)
        return None
    if not isinstance(data, dict):
        logger.warning("Ответ AI — не JSON-объект: %r", raw)
        return None

    title = str(data.get("title") or "").strip()
    if not title:
        logger.warning("AI не вернул заголовок: %r", raw)
        return None
    return {
        "title": title[:140],
        "summary": (str(data.get("summary") or "").strip()[:300]) or None,
        "body": str(data.get("body") or "").strip(),
    }
