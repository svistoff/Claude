"""Клиент сервиса распознавания капчи (rucaptcha / 2captcha, совместимый API).

Реализован метод для Yandex SmartCaptcha (token-based): по sitekey и URL страницы
сервис возвращает токен, который вставляется в скрытое поле капчи, после чего
страница проходит проверку.

ВАЖНО: точный способ вставки токена и сабмита зависит от текущей верстки
SmartCaptcha и требует проверки на живой капче. HTTP-обмен с сервисом реализован
по классическому API in.php/res.php (rucaptcha/2captcha-совместимый).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger("posmon.captcha")

# База API совместимых сервисов (rucaptcha.com, 2captcha.com).
_ENDPOINTS = {
    "rucaptcha": "https://rucaptcha.com",
    "anticaptcha": "https://api.anti-captcha.com",  # иной протокол — см. примечание
    "2captcha": "https://2captcha.com",
}


class CaptchaError(Exception):
    pass


class CaptchaSolver:
    """Решатель Yandex SmartCaptcha через rucaptcha/2captcha (in.php/res.php)."""

    def __init__(self, api_key: str, provider: str = "rucaptcha", timeout: float = 180.0) -> None:
        self.api_key = api_key
        self.provider = provider
        self.base = _ENDPOINTS.get(provider, _ENDPOINTS["rucaptcha"])
        self.timeout = timeout

    async def solve_yandex(self, sitekey: str, page_url: str) -> str:
        """Вернуть токен решения Yandex SmartCaptcha (или бросить CaptchaError)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base}/in.php",
                params={
                    "key": self.api_key,
                    "method": "yandex",
                    "sitekey": sitekey,
                    "pageurl": page_url,
                    "json": "1",
                },
            )
            data = resp.json()
            if data.get("status") != 1:
                raise CaptchaError(f"in.php: {data.get('request')}")
            task_id = data["request"]

        deadline = asyncio.get_event_loop().time() + self.timeout
        async with httpx.AsyncClient(timeout=30.0) as client:
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(5)
                r = await client.get(
                    f"{self.base}/res.php",
                    params={"key": self.api_key, "action": "get", "id": task_id, "json": "1"},
                )
                d = r.json()
                if d.get("status") == 1:
                    return d["request"]
                if d.get("request") != "CAPCHA_NOT_READY":
                    raise CaptchaError(f"res.php: {d.get('request')}")
        raise CaptchaError("timeout ожидания решения капчи")
