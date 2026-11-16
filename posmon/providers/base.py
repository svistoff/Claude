"""Единый контракт провайдеров сбора выдачи."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..domain.results import CheckStatus, SerpResult


@dataclass(slots=True)
class SearchRequest:
    """Параметры одной выборки выдачи."""

    query: str
    region_lr: int = 54          # 54 = Екатеринбург
    device: str = "desktop"      # desktop | mobile
    depth: int = 50              # сколько результатов запрашивать (ТОП-N)
    page_size: int = 10          # результатов на страницу (для пагинации браузера)


@dataclass(slots=True)
class SerpFetch:
    """Результат одной выборки выдачи в единой схеме (любой источник).

    ``results`` — полная выдача (органика + реклама + колдунщики), в порядке
    показа, с проставленным ``result_type``. Позиция сайта из неё вычисляется
    отдельно (:mod:`posmon.domain.position`).
    """

    status: CheckStatus
    results: list[SerpResult] = field(default_factory=list)
    search_url: str | None = None
    source: str = "api"                  # api | browser
    parser_version: str | None = None
    raw_html: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None

    @property
    def ok(self) -> bool:
        """Выдача пригодна для записи позиции (SUCCESS/NOT_FOUND определяется позже)."""
        return self.status not in (
            CheckStatus.ERROR,
            CheckStatus.BLOCKED,
            CheckStatus.CAPTCHA,
        )


@runtime_checkable
class SearchProvider(Protocol):
    """Провайдер сбора выдачи.

    Реализация НЕ должна возвращать «пустую» выдачу как успех: если страница не
    загрузилась / обнаружена капча / выдача неполна — возвращается статус
    ERROR/BLOCKED/CAPTCHA, а не фальшивый результат (разделы 14, 36 ТЗ).
    """

    source: str

    async def fetch(self, request: SearchRequest) -> SerpFetch:
        ...
