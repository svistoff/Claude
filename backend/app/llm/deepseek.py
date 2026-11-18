"""Провайдер DeepSeek (официальный API, OpenAI-совместимый /chat/completions).

Стриминг через httpx. Аккумулирует дельты tool_calls в готовые вызовы,
извлекает usage (включая prompt_cache_hit_tokens для учёта стоимости).

Надёжность сети:
- раздельные таймауты: короткий connect, длинный read (thinking + большой
  контекст дают долгий первый токен);
- повтор запроса при обрыве/таймауте, если модель ещё ничего не сказала
  (иначе пользователь увидел бы продублированный текст);
- понятный текст ошибки: у httpx сообщение бывает пустым, поэтому класс
  исключения печатается всегда.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import LLMProvider, ToolCall

log = logging.getLogger(__name__)

# Ошибки, при которых запрос имеет смысл повторить: обрыв/таймаут до первых данных.
RETRYABLE: tuple[type[Exception], ...] = (
    httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
    httpx.WriteError, httpx.RemoteProtocolError, httpx.ReadError,
)


class DeepSeekProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        request_timeout: int = 120,
        extra_headers: dict | None = None,
        connect_timeout: int = 15,
        retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout
        self.extra_headers = extra_headers or {}
        self.connect_timeout = connect_timeout
        self.retries = max(0, retries)

    def _timeout(self) -> httpx.Timeout:
        """Раздельные таймауты.

        read — ожидание очередного байта от модели. При большом контексте и
        включённом thinking первый токен может идти минутами, поэтому read
        задаётся отдельно от connect: короткий connect быстро отсекает мёртвую
        сеть, а долгий read не рвёт нормальный «долго думающий» ответ.
        """
        return httpx.Timeout(connect=self.connect_timeout,
                             read=self.request_timeout,
                             write=max(60, self.connect_timeout),
                             pool=self.connect_timeout)

    @staticmethod
    def _describe(exc: Exception) -> str:
        """Понятное описание сетевой ошибки.

        У httpx сообщение бывает пустым (например, ReadTimeout, поднятый из
        socket.timeout: str(socket.timeout()) == ''). Поэтому класс исключения
        добавляем всегда — иначе пользователь видит «Сетевая ошибка DeepSeek: »
        без причины.
        """
        detail = str(exc).strip()
        mapping = {
            "ReadTimeout": "модель не прислала данные за отведённое время (таймаут чтения)",
            "ConnectTimeout": "не удалось подключиться к API за отведённое время",
            "PoolTimeout": "исчерпан пул соединений",
            "ConnectError": "нет соединения с api.deepseek.com (сеть, DNS или прокси)",
            "RemoteProtocolError": "сервер разорвал соединение до конца ответа",
            "ReadError": "соединение оборвалось при чтении ответа",
        }
        hint = mapping.get(type(exc).__name__, "")
        parts = [p for p in (hint, detail) if p]
        return f"{type(exc).__name__}: " + (" · ".join(parts) if parts else "сетевая ошибка")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self.api_key:
            yield {"type": "error", "message": "DEEPSEEK_API_KEY не задан."}
            return

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        url = f"{self.base_url}/chat/completions"

        # Аккумуляторы дельт tool_calls: index -> {id,name,args_str}.
        tool_acc: dict[int, dict[str, str]] = {}
        finish_reason = "stop"

        for attempt in range(self.retries + 1):
            # Повторяем только если модель ещё ничего не сказала: иначе пользователь
            # увидит продублированный текст. Аккумулятор вызовов сбрасываем.
            tool_acc = {}
            emitted = False
            try:
                async with httpx.AsyncClient(timeout=self._timeout()) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "ignore")
                            yield {"type": "error",
                                   "message": f"DeepSeek API {resp.status_code}: {body[:500]}"}
                            return
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[len("data:"):].strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            emitted = True

                            # usage приходит в финальном chunk (может быть без choices).
                            if chunk.get("usage"):
                                u = chunk["usage"]
                                yield {
                                    "type": "usage",
                                    "input": u.get("prompt_tokens", 0),
                                    "output": u.get("completion_tokens", 0),
                                    "cache_hit": u.get("prompt_cache_hit_tokens", 0),
                                }

                            for choice in chunk.get("choices", []):
                                delta = choice.get("delta", {})
                                if delta.get("content"):
                                    yield {"type": "text", "delta": delta["content"]}
                                for tc in delta.get("tool_calls", []) or []:
                                    idx = tc.get("index", 0)
                                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                                    if tc.get("id"):
                                        slot["id"] = tc["id"]
                                    fn = tc.get("function", {})
                                    if fn.get("name"):
                                        slot["name"] = fn["name"]
                                    if fn.get("arguments"):
                                        slot["args"] += fn["arguments"]
                                if choice.get("finish_reason"):
                                    finish_reason = choice["finish_reason"]
                break  # поток завершился штатно
            except RETRYABLE as exc:
                last_error = exc
                can_retry = (not emitted) and attempt < self.retries
                log.warning("DeepSeek сеть (%s), попытка %s/%s, повтор=%s",
                            self._describe(exc), attempt + 1, self.retries + 1, can_retry)
                if not can_retry:
                    where = "после начала ответа" if emitted else ""
                    yield {"type": "error",
                           "message": f"Сетевая ошибка DeepSeek: {self._describe(exc)}"
                                      f"{' · ' + where if where else ''}"}
                    return
                yield {"type": "retry", "attempt": attempt + 2,
                       "of": self.retries + 1, "reason": self._describe(exc)}
                await asyncio.sleep(2 ** attempt)
            except httpx.HTTPError as exc:
                yield {"type": "error", "message": f"Сетевая ошибка DeepSeek: {self._describe(exc)}"}
                return

        if tool_acc:
            calls: list[ToolCall] = []
            for idx in sorted(tool_acc):
                slot = tool_acc[idx]
                if not slot["name"]:
                    continue
                try:
                    args = json.loads(slot["args"]) if slot["args"].strip() else {}
                except json.JSONDecodeError:
                    args = {"_raw": slot["args"]}
                calls.append(ToolCall(id=slot["id"] or f"call_{idx}",
                                      name=slot["name"], arguments=args))
            if calls:
                yield {"type": "tool_calls", "calls": calls}

        yield {"type": "finish", "reason": finish_reason}
