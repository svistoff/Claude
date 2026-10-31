"""Вызов OpenAI-совместимого API (по умолчанию DeepSeek)."""

from __future__ import annotations

import httpx


class LLMError(Exception):
    pass


# Рассуждающие модели (DeepSeek V4 flash/pro, *-reasoner и т.п.) тратят max_tokens
# сначала на скрытые рассуждения. Если лимит мал, рассуждение съедает его целиком,
# и в content приходит пустая строка с finish_reason="length". Поэтому лимит
# по умолчанию щедрый, а при обрыве по длине делаем один повтор с большим запасом.
DEFAULT_MAX_TOKENS = 3000
RETRY_MAX_TOKENS = 8000


async def complete(api_key: str, base_url: str, model: str, system: str, user: str,
                   max_tokens: int = DEFAULT_MAX_TOKENS, json_mode: bool = False) -> str:
    content, finish = await _request(api_key, base_url, model, system, user, max_tokens, json_mode)
    if not content and finish == "length" and max_tokens < RETRY_MAX_TOKENS:
        content, finish = await _request(api_key, base_url, model, system, user,
                                         RETRY_MAX_TOKENS, json_mode)
    if not content and finish == "length":
        raise LLMError("модель упёрлась в лимит токенов, не дописав ответ "
                       "(похоже на рассуждающую модель — смени LLM_MODEL или повтори позже)")
    if not content and finish == "content_filter":
        raise LLMError("ответ заблокирован фильтром провайдера")
    return content


async def _request(api_key: str, base_url: str, model: str, system: str, user: str,
                   max_tokens: int, json_mode: bool) -> tuple[str, str]:
    if not api_key:
        raise LLMError("LLM_API_KEY не задан в .env")
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 400 and json_mode:  # провайдер не знает response_format
                payload.pop("response_format")
                r = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise LLMError(f"сетевая ошибка: {exc}") from exc
    if r.status_code != 200:
        raise LLMError(f"API {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        choice = data["choices"][0]
        content = (choice["message"].get("content") or "").strip()
    except (KeyError, IndexError) as exc:
        raise LLMError(f"неожиданный ответ API: {str(data)[:300]}") from exc
    return content, choice.get("finish_reason") or ""
