"""Провайдер DeepSeek (официальный API, OpenAI-совместимый /chat/completions).

Стриминг через httpx. Аккумулирует дельты tool_calls в готовые вызовы,
извлекает usage (включая prompt_cache_hit_tokens для учёта стоимости).
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .base import LLMProvider, ToolCall


class DeepSeekProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        request_timeout: int = 120,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout

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
        }
        url = f"{self.base_url}/chat/completions"

        # Аккумуляторы дельт tool_calls: index -> {id,name,args_str}.
        tool_acc: dict[int, dict[str, str]] = {}
        finish_reason = "stop"

        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
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
        except httpx.HTTPError as exc:
            yield {"type": "error", "message": f"Сетевая ошибка DeepSeek: {exc}"}
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
