"""Вызов OpenAI API для переписывания текста поста."""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from bot.config import config

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.openai_api_key, base_url=config.openai_base_url)
    return _client


async def rewrite_text(original_text: str, system_prompt: str) -> str:
    """Отправляет исходный текст в OpenAI с заданным системным промтом и возвращает новый текст."""
    client = _get_client()
    response = await client.chat.completions.create(
        model=config.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": original_text},
        ],
    )
    new_text = response.choices[0].message.content
    if not new_text or not new_text.strip():
        raise RuntimeError("OpenAI вернул пустой ответ")
    return new_text.strip()
