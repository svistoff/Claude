"""Расшифровка голосовых: OpenAI-совместимый /audio/transcriptions (Groq, OpenAI…)."""

from __future__ import annotations

import httpx


class STTError(Exception):
    pass


async def transcribe(api_key: str, base_url: str, model: str, audio: bytes,
                     filename: str = "voice.ogg", language: str = "ru") -> str:
    if not api_key:
        raise STTError("STT_API_KEY не задан в .env")
    url = f"{base_url.rstrip('/')}/audio/transcriptions"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                url, headers={"Authorization": f"Bearer {api_key}"},
                data={"model": model, "language": language, "response_format": "json"},
                files={"file": (filename, audio, "audio/ogg")})
    except httpx.HTTPError as exc:
        raise STTError(f"сетевая ошибка: {exc}") from exc
    if r.status_code != 200:
        raise STTError(f"API {r.status_code}: {r.text[:300]}")
    try:
        return (r.json().get("text") or "").strip()
    except ValueError as exc:
        raise STTError(f"неожиданный ответ API: {r.text[:300]}") from exc
