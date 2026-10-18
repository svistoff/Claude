"""Вызов OpenAI-совместимого API (по умолчанию DeepSeek)."""

from __future__ import annotations

import httpx


class LLMError(Exception):
    pass


async def complete(api_key: str, base_url: str, model: str, system: str, user: str,
                   max_tokens: int = 800) -> str:
    if not api_key:
        raise LLMError("LLM_API_KEY не задан в .env")
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(url, json=payload,
                                  headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        raise LLMError(f"сетевая ошибка: {exc}") from exc
    if r.status_code != 200:
        raise LLMError(f"API {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError) as exc:
        raise LLMError(f"неожиданный ответ API: {str(data)[:300]}") from exc
