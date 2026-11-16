"""Парсер HTML-выдачи Яндекса → список результатов с типами.

Best-effort: селекторы и эвристики отражают известную структуру десктопной
выдачи Яндекса и ТРЕБУЮТ подтверждения на живой странице (верстка меняется).
Классификация блоков по порядку: реклама сверху/снизу, органика, блок Бизнеса,
прочие вертикали (см. раздел 3.2 ТЗ).

Отделён от браузерного провайдера, чтобы логику можно было проверять на
сохранённом HTML без запуска браузера.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ..domain.results import ResultType, SerpResult

_AD_TEXT_MARKERS = ("реклама",)
_BUSINESS_CLASS_MARKERS = ("compan", "orgs", "mmorg", "business", "geo")


def _classify(class_str: str, text_head: str, seen_organic: bool) -> ResultType:
    low = class_str.lower()
    t = text_head.lower()
    if any(m in t for m in _AD_TEXT_MARKERS) or "adv" in low or "direct" in low:
        return ResultType.AD_TOP if not seen_organic else ResultType.AD_BOTTOM
    if any(m in low for m in _BUSINESS_CLASS_MARKERS):
        return ResultType.BUSINESS
    if "video" in low:
        return ResultType.VIDEO
    if "image" in low:
        return ResultType.IMAGES
    if "market" in low or "product" in low:
        return ResultType.MARKET
    return ResultType.ORGANIC


def _extract_link(item) -> tuple[str | None, str | None]:
    a = (
        item.select_one("a.OrganicTitle-Link")
        or item.select_one(".organic__url")
        or item.select_one('a.Link[href^="http"]')
        or item.select_one('a[href^="http"]')
    )
    if a and a.get("href"):
        return a["href"], a.get_text(" ", strip=True) or None
    return None, None


def parse_serp_html(html: str) -> list[SerpResult]:
    """Разобрать HTML выдачи в упорядоченный список результатов с result_type."""
    soup = BeautifulSoup(html or "", "html.parser")
    items = soup.select("li.serp-item")
    if not items:
        items = soup.select(".serp-item, .Organic")

    results: list[SerpResult] = []
    seen_organic = False
    pos = 0
    for it in items:
        url, title = _extract_link(it)
        if not url:
            continue  # служебные блоки без ссылки пропускаем
        text_head = it.get_text(" ", strip=True)[:120]
        class_str = " ".join(it.get("class", []))
        rtype = _classify(class_str, text_head, seen_organic)
        if rtype == ResultType.ORGANIC:
            seen_organic = True
        pos += 1
        results.append(SerpResult(url=url, result_type=rtype, title=title, raw_position=pos))
    return results
