"""Браузерный провайдер (Playwright + Chromium) — персонализированные профили.

Персонализированные профили (Екатеринбуржец, Приезжий) требуют живой сессии с
сохранённым состоянием браузера, поэтому собираются браузером с VPS + сервисом
распознавания капчи (раздел 1.2 ТЗ v2).

Статус: каркас. Сетевой сбор и парсинг HTML-выдачи Яндекса требуют проверки на
живой выдаче с реальными профилями и не могут быть протестированы в CI. Пока
парсер не подтверждён, провайдер БЕЗОПАСНО возвращает статус ERROR, а не
фальшивую позицию (разделы 14, 36 ТЗ). Метод :func:`parse_serp_html`
дорабатывается на реальной верстке.
"""
from __future__ import annotations

import time

from ..domain.results import CheckStatus, SerpResult
from .base import SearchRequest, SerpFetch

PARSER_VERSION = "yandex-html-0"


def parse_serp_html(html: str) -> list[SerpResult]:
    """Разбор HTML-выдачи Яндекса в список результатов с проставленным result_type.

    TODO (доработать на живой выдаче): разметить organic / ad_top / ad_bottom /
    business / maps / video / market / fast_answer / other по DOM-структуре SERP.
    Пока не реализовано — сознательно, чтобы не отдавать неверную разметку.
    """
    raise NotImplementedError("HTML SERP parser ещё не подтверждён на живой выдаче")


def is_captcha(html: str) -> bool:
    """Признак страницы капчи Яндекса (SmartCaptcha / checkcaptcha)."""
    markers = ("checkcaptcha", "SmartCaptcha", "showcaptcha", "captcha__image")
    lowered = html.lower()
    return any(m.lower() in lowered for m in markers)


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
    ) -> None:
        self.profile_path = profile_path
        self.device = device
        self.proxy = proxy
        self.captcha_api_key = captcha_api_key
        self.captcha_provider = captcha_provider

    async def fetch(self, request: SearchRequest) -> SerpFetch:
        started = time.monotonic()
        try:
            html, search_url = await self._load_serp(request)
        except NotImplementedError as exc:
            return SerpFetch(
                status=CheckStatus.ERROR,
                source=self.source,
                error_code="browser_not_configured",
                error_message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 — сетевые/браузерные сбои → ERROR, не позиция
            return SerpFetch(
                status=CheckStatus.ERROR,
                source=self.source,
                error_code="browser_error",
                error_message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        if is_captcha(html):
            return SerpFetch(
                status=CheckStatus.CAPTCHA,
                source=self.source,
                search_url=search_url,
                error_code="captcha",
                error_message="обнаружена капча Яндекса",
                duration_ms=duration_ms,
            )
        results = parse_serp_html(html)
        status = CheckStatus.SUCCESS if results else CheckStatus.NOT_FOUND
        return SerpFetch(
            status=status,
            results=results,
            search_url=search_url,
            source=self.source,
            parser_version=PARSER_VERSION,
            raw_html=html,
            duration_ms=duration_ms,
        )

    async def _load_serp(self, request: SearchRequest) -> tuple[str, str]:
        """Загрузить выдачу через Playwright с persistent-контекстом профиля.

        Реализуется на живой среде: launch_persistent_context(self.profile_path),
        эмуляция устройства, регион через &lr, пейсинг и пагинация до глубины,
        решение капчи через сервис при обнаружении. Возвращает (html, url).
        """
        raise NotImplementedError(
            "браузерный сбор дорабатывается на живой выдаче (Playwright + профили + капча)"
        )
