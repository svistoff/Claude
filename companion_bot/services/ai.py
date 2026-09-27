"""Вызовы OpenAI: ответ персонажа, обновление долгосрочной памяти, проактивное сообщение."""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from companion_bot.config import config
from companion_bot.persona import Persona

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

_SUMMARY_SYSTEM_PROMPT = (
    "Ты обновляешь краткую память AI-персонажа о пользователе для будущих "
    "разговоров. Тебе дана текущая память (может быть пустой) и новый "
    "фрагмент переписки. Верни обновлённую память: краткие буллеты с важными "
    "фактами о пользователе (имя, интересы, работа, важные события, "
    "предпочтения, договорённости). Сохраняй прежние факты, если они не "
    "устарели, добавляй новые, убирай неважные детали. Не пиши ничего, кроме "
    "самого списка фактов. Пиши по-русски, кратко."
)

_PROACTIVE_INSTRUCTION = (
    "\n\nТы сама начинаешь разговор, потому что давно не общались с "
    "пользователем. Напиши одно короткое, тёплое сообщение первой — спроси, "
    "как дела, или расскажи что-то от себя (мысль, настроение). Никогда не "
    "упоминай деньги, донаты или оплату в этом сообщении."
)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.openai_api_key, base_url=config.openai_base_url)
    return _client


def _system_content(persona: Persona, memory_summary: str) -> str:
    content = persona.system_prompt
    if memory_summary:
        content += (
            "\n\nВот что ты помнишь о пользователе из прошлых разговоров "
            f"(используй естественно, не зачитывай как список):\n{memory_summary}"
        )
    return content


async def generate_reply(
    persona: Persona,
    history: list[dict[str, str]],
    user_message: str,
    memory_summary: str = "",
) -> str:
    client = _get_client()
    messages = [{"role": "system", "content": _system_content(persona, memory_summary)}]
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


async def summarize_memory(current_summary: str, new_messages_text: str) -> str:
    client = _get_client()
    user_content = (
        f"Текущая память:\n{current_summary or '(пока пусто)'}\n\n"
        f"Новый фрагмент переписки:\n{new_messages_text}"
    )
    response = await client.chat.completions.create(
        model=config.openai_model,
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )
    summary = response.choices[0].message.content
    if not summary or not summary.strip():
        raise RuntimeError("OpenAI вернул пустую память")
    return summary.strip()


async def generate_proactive_message(persona: Persona, memory_summary: str) -> str:
    client = _get_client()
    system_content = _system_content(persona, memory_summary) + _PROACTIVE_INSTRUCTION

    response = await client.chat.completions.create(
        model=config.openai_model,
        messages=[{"role": "system", "content": system_content}],
        temperature=0.9,
    )
    text = response.choices[0].message.content
    if not text or not text.strip():
        raise RuntimeError("OpenAI вернул пустое сообщение")
    return text.strip()
