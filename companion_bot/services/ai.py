"""Вызов OpenAI для генерации ответа персонажа с учётом истории диалога."""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from companion_bot.config import config
from companion_bot.persona import Persona

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.openai_api_key, base_url=config.openai_base_url)
    return _client


async def generate_reply(
    persona: Persona, history: list[dict[str, str]], user_message: str
) -> str:
    client = _get_client()
    messages = [{"role": "system", "content": persona.system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    response = await client.chat.completions.create(
        model=config.openai_model,
        messages=messages,
        temperature=0.9,
    )
    reply = response.choices[0].message.content
    if not reply or not reply.strip():
        raise RuntimeError("OpenAI вернул пустой ответ")
    return reply.strip()
