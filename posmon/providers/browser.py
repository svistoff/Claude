"""Браузерный провайдер (Playwright + Chromium) — персонализированные профили.

Возможности (раздел 1.2 ТЗ):
- персистентный профиль браузера на каждый профиль (cookies/состояние копятся);
- эмуляция устройства desktop/mobile;
- регион через параметр lr;
- пагинация до заданной глубины с пейсингом (пауза между страницами);
- детект капчи и решение через сервис (rucaptcha/2captcha), иначе статус CAPTCHA;
- сохранение HTML/скриншота для аудита;
- любая браузерная/сетевая ошибка → ERROR (не фальшивая позиция).

Парсинг HTML вынесен в :mod:`posmon.providers.serp_html`. Селекторы парсера и
способ решения капчи ТРЕБУЮТ подтверждения на живой выдаче.
"""
from __future__ import annotations

import logging
import math
import random
import time
from pathlib import Path
from urllib.parse import quote_plus

from ..domain.results import CheckStatus, SerpResult
from .base import SearchRequest, SerpFetch
from .captcha import CaptchaError, CaptchaSolver
from .serp_html import parse_serp_html

logger = logging.getLogger("posmon.browser")
PARSER_VERSION = "yandex-html-1"

_CAPTCHA_MARKERS = ("checkcaptcha", "smartcaptcha", "showcaptcha", "captcha__image", "smart-token")


def is_captcha(html: str, url: str = "") -> bool:
    blob = (html + " " + url).lower()
    return any(m in blob for m in _CAPTCHA_MARKERS)


class BrowserProvider:
    source = "browser"

    def __init__(
        self,
        profile_path: str,
        *,
        device: str = "desktop",
        proxy: str | None = None,
        captcha_api_key: str | None = None,
        captcha_provider: str | None = None,
        headless: bool = True,
        pace: tuple[float, float] = (15.0, 40.0),
        nav_timeout_ms: int = 45000,
        artifacts_dir: str | None = None,
        save_html: bool = True,
        save_screenshot: bool = False,
    ) -> None:
        self.profile_path = profile_path
        self.device = device
        self.proxy = proxy
        self.captcha_api_key = captcha_api_key
        self.captcha_provider = captcha_provider
        self.headless = headless
        self.pace = pace
        self.nav_timeout_ms = nav_timeout_ms
        self.artifacts_dir = artifacts_dir
        self.save_html = save_html
        self.save_screenshot = save_screenshot

    def _search_url(self, request: SearchRequest, page_index: int) -> str:
        return (
            f"https://yandex.ru/search/?text={quote_plus(request.query)}"
            f"&lr={request.region_lr}&p={page_index}"
        )

    async def fetch(self, request: SearchRequest) -> SerpFetch:
        started = time.monotonic()
        try:
            results, search_url, html = await self._collect(request)
        except CaptchaError as exc:
            return self._fail(CheckStatus.CAPTCHA, "captcha", str(exc), started)
        except Exception as exc:  # noqa: BLE001 — браузер/сеть → ERROR, не позиция
            logger.exception("Браузерный сбор упал: %s", request.query)
            return self._fail(CheckStatus.ERROR, "browser_error", str(exc), started)

        duration_ms = int((time.monotonic() - started) * 1000)
        if html is not None and is_captcha(html, search_url):
            return SerpFetch(
                status=CheckStatus.CAPTCHA, source=self.source, search_url=search_url,
                error_code="captcha", error_message="капча не решена", duration_ms=duration_ms,
            )
        status = CheckStatus.SUCCESS if results else CheckStatus.NOT_FOUND
        return SerpFetch(
            status=status, results=results, search_url=search_url, source=self.source,
            parser_version=PARSER_VERSION, raw_html=html, duration_ms=duration_ms,
        )

    def _fail(self, status: CheckStatus, code: str, msg: str, started: float) -> SerpFetch:
        return SerpFetch(
            status=status, source=self.source, error_code=code, error_message=msg,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def _collect(self, request: SearchRequest) -> tuple[list[SerpResult], str, str | None]:
        from playwright.async_api import async_playwright

        pages_count = max(1, math.ceil(request.depth / request.page_size))
        Path(self.profile_path).mkdir(parents=True, exist_ok=True)

        all_results: list[SerpResult] = []
        first_url = ""
        last_html: str | None = None

        async with async_playwright() as p:
            context_kwargs: dict = {"headless": self.headless}
            if self.proxy:
                context_kwargs["proxy"] = {"server": self.proxy}
            if self.device == "mobile":
                context_kwargs.update(p.devices["Pixel 5"])
            else:
                context_kwargs["viewport"] = {"width": 1366, "height": 900}

            context = await p.chromium.launch_persistent_context(self.profile_path, **context_kwargs)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                page.set_default_navigation_timeout(self.nav_timeout_ms)

                for i in range(pages_count):
                    url = self._search_url(request, i)
                    if i == 0:
                        first_url = url
                    await page.goto(url, wait_until="domcontentloaded")
                    html = await page.content()

                    if is_captcha(html, page.url):
                        solved = await self._try_solve_captcha(page)
                        html = await page.content()
                        if not solved or is_captcha(html, page.url):
                            last_html = html
                            break  # не решили — вернём CAPTCHA выше

                    last_html = html
                    page_results = parse_serp_html(html)
                    for r in page_results:
                        r.raw_position = len(all_results) + 1
                        all_results.append(r)

                    await self._save_artifacts(request, i, html, page)

                    if len(all_results) >= request.depth or not page_results:
                        break
                    await self._pace()
            finally:
                await context.close()

        return all_results[: request.depth], first_url, last_html

    async def _try_solve_captcha(self, page) -> bool:
        """Попытаться решить SmartCaptcha через сервис. True — если отправили токен."""
        if not (self.captcha_api_key and self.captcha_provider):
            return False
        try:
            sitekey = await page.get_attribute("[data-sitekey]", "data-sitekey")
            if not sitekey:
                return False
            solver = CaptchaSolver(self.captcha_api_key, self.captcha_provider)
            token = await solver.solve_yandex(sitekey, page.url)
            await page.evaluate(
                "(t) => { const el = document.querySelector('input[name=smart-token]');"
                " if (el) { el.value = t; el.dispatchEvent(new Event('change', {bubbles:true})); } }",
                token,
            )
            # submit формы капчи, если есть
            form = await page.query_selector("form")
            if form:
                await form.evaluate("f => f.submit()")
                await page.wait_for_load_state("domcontentloaded")
            return True
        except CaptchaError:
            raise
        except Exception:  # noqa: BLE001 — не удалось вставить токен → считаем не решённой
            logger.exception("Ошибка при решении капчи")
            return False

    async def _pace(self) -> None:
        import asyncio

        await asyncio.sleep(random.uniform(self.pace[0], self.pace[1]))

    async def _save_artifacts(self, request: SearchRequest, page_index: int, html: str, page) -> None:
        if not (self.save_html or self.save_screenshot) or not self.artifacts_dir:
            return
        try:
            d = Path(self.artifacts_dir)
            d.mkdir(parents=True, exist_ok=True)
            stamp = f"{int(time.time())}_{abs(hash(request.query)) % 10000}_p{page_index}"
            if self.save_html:
                (d / f"{stamp}.html").write_text(html, encoding="utf-8")
            if self.save_screenshot:
                await page.screenshot(path=str(d / f"{stamp}.png"), full_page=True)
        except Exception:  # noqa: BLE001 — сохранение артефактов не должно ронять сбор
            logger.warning("Не удалось сохранить артефакты выдачи", exc_info=True)
