"""Расчёт позиции сайта по сохранённой выдаче (сердце системы).

Раздел 3 ТЗ v2:
- позиция считается по ОРГАНИЧЕСКОЙ выдаче;
- реклама и колдунщики (Бизнес, Карты, видео, товары, ...) пропускаются;
- при нескольких вхождениях одного домена берётся ЛУЧШАЯ (высшая) позиция;
- если сайт не найден в пределах глубины — позиция ``None`` (NOT_FOUND);
- для локальных запросов дополнительно и отдельно считается позиция в блоке
  Яндекс.Бизнеса.

Функции чистые: принимают список :class:`SerpResult` и возвращают числа/None,
что позволяет пересчитать позицию из сохранённой выдачи при изменении правил.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .normalize import MATCH_DOMAIN, MatchMode, host_matches
from .results import ResultType, SerpResult

# Рекламные типы, учитываемые в «сколько рекламы над тобой» (раздел 1.5 ТЗ).
_AD_TYPES = (ResultType.AD_TOP,)


def _best_rank_within(
    serp: Iterable[SerpResult],
    result_type: ResultType,
    site_value: str,
    match_mode: MatchMode,
) -> int | None:
    """Лучшая (наименьшая) позиция сайта среди результатов заданного типа.

    Позиция — это 1-based порядковый номер результата ВНУТРИ подпоследовательности
    результатов данного типа (например, только органических). Реклама и
    колдунщики других типов слотов не занимают. Первое совпадение по домену и
    даёт лучшую позицию (дубли ниже игнорируются автоматически).
    """
    rank = 0
    for result in serp:
        if result.result_type != result_type:
            continue
        rank += 1
        if host_matches(result.url, site_value, match_mode):
            return rank
    return None


def compute_position(
    serp: Iterable[SerpResult],
    site_value: str,
    match_mode: MatchMode = MATCH_DOMAIN,
) -> int | None:
    """Органическая позиция сайта, либо ``None`` если сайт не найден."""
    return _best_rank_within(serp, ResultType.ORGANIC, site_value, match_mode)


def compute_business_position(
    serp: Iterable[SerpResult],
    site_value: str,
    match_mode: MatchMode = MATCH_DOMAIN,
) -> int | None:
    """Позиция сайта в блоке Яндекс.Бизнеса, либо ``None``.

    Отдельная метрика для локальных запросов; с органической позицией не
    смешивается.
    """
    return _best_rank_within(serp, ResultType.BUSINESS, site_value, match_mode)


def compute_visual_position(
    serp: Iterable[SerpResult],
    site_value: str,
    match_mode: MatchMode = MATCH_DOMAIN,
) -> int | None:
    """«Боевая» визуальная позиция: номер органического результата сайта на
    странице, считая ВСЕ блоки над ним (реклама, колдунщики).

    Показывает реальную глубину скролла живого пользователя (раздел 1.5 ТЗ).
    Для ночной API-выдачи (только органика) совпадает с органической позицией.
    ``None``, если органического результата сайта нет.
    """
    for idx, result in enumerate(serp, start=1):
        if result.result_type == ResultType.ORGANIC and host_matches(
            result.url, site_value, match_mode
        ):
            return idx
    return None


def count_ads_above(
    serp: Iterable[SerpResult],
    site_value: str,
    match_mode: MatchMode = MATCH_DOMAIN,
) -> int | None:
    """Сколько рекламных блоков (Директ) стоит над органическим результатом сайта.

    ``None``, если органического результата сайта нет.
    """
    ads = 0
    for result in serp:
        if result.result_type in _AD_TYPES:
            ads += 1
        elif result.result_type == ResultType.ORGANIC and host_matches(
            result.url, site_value, match_mode
        ):
            return ads
    return None


@dataclass(slots=True)
class SiteMatch:
    """Результат сопоставления одного сайта с одной выборкой выдачи."""

    site_value: str
    position: int | None
    business_position: int | None = None
    visual_position: int | None = None
    ads_above: int | None = None

    @property
    def found(self) -> bool:
        return self.position is not None


def match_site(
    serp: Iterable[SerpResult],
    site_value: str,
    match_mode: MatchMode = MATCH_DOMAIN,
    *,
    with_business: bool = False,
    with_visual: bool = False,
) -> SiteMatch:
    """Сопоставить сайт с выдачей.

    - всегда: органическая позиция;
    - ``with_business`` (локальные запросы): позиция в блоке Бизнеса;
    - ``with_visual`` (боевой режим): визуальная позиция и число реклам над сайтом.

    Одну выдачу можно сопоставить с любым числом сайтов без повторного запроса
    к Яндексу (раздел 2 ТЗ: единица работы — выборка выдачи, а не проверка сайта).
    """
    serp = list(serp)  # позволяем передавать генератор и пройти несколько раз
    position = compute_position(serp, site_value, match_mode)
    business_position = (
        compute_business_position(serp, site_value, match_mode) if with_business else None
    )
    visual_position = compute_visual_position(serp, site_value, match_mode) if with_visual else None
    ads_above = count_ads_above(serp, site_value, match_mode) if with_visual else None
    return SiteMatch(
        site_value=site_value,
        position=position,
        business_position=business_position,
        visual_position=visual_position,
        ads_above=ads_above,
    )
