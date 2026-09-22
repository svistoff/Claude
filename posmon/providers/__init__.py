"""Провайдеры сбора выдачи.

Единый интерфейс :class:`SearchProvider` с реализациями:
- :class:`YandexApiProvider`  — официальный Yandex Search API (непесонализированные профили);
- :class:`BrowserProvider`    — Playwright + Chromium (персонализированные профили);
- :class:`MockProvider`       — детерминированный мок для тестов/разработки.

Результат любого провайдера — :class:`SerpFetch` в единой схеме, независимо от
источника (раздел 1.4 ТЗ v2).
"""
from .base import SearchProvider, SearchRequest, SerpFetch

__all__ = ["SearchProvider", "SearchRequest", "SerpFetch"]
