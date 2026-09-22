"""Провайдер официального Yandex Search API (непесонализированные профили).

Реализован классический XML-эндпоинт (`/search/xml`), возвращающий органическую
выдачу. Реклама и колдунщики через этот API обычно не отдаются, поэтому все
результаты размечаются как ``organic``.

ВАЖНО: точный эндпоинт и способ авторизации зависят от типа доступа в аккаунте
(классический XML vs Yandex Cloud Search API v2). HTTP-вызов вынесен в
:meth:`_request`, чтобы его можно было адаптировать под аккаунт без изменения
парсинга. Парсер (:func:`parse_yandex_xml`) чистый и покрыт тестами.
"""
from __future__ import annotations

import time
from xml.etree import ElementTree as ET

import httpx

from ..domain.results import CheckStatus, ResultType, SerpResult
from .base import SearchRequest, SerpFetch

PARSER_VERSION = "yandex-xml-1"

# Коды ошибок Yandex XML, которые означают временную/блокирующую проблему,
# а не «сайт не найден». При них позиция НЕ записывается (разделы 14, 36 ТЗ).
_BLOCKING_ERROR_CODES = {"55"}       # 55 = превышен лимит запросов
_NOT_FOUND_ERROR_CODES = {"15"}      # 15 = искомая комбинация слов нигде не встречается
_TEMP_ERROR_CODES = {"1", "10", "100", "111"}


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    text = "".join(el.itertext()).strip()
    return text or None


def parse_yandex_xml(xml_text: str) -> tuple[CheckStatus, list[SerpResult], str | None, str | None]:
    """Разобрать XML-ответ Yandex Search API.

    Возвращает ``(status, results, error_code, error_message)``.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return CheckStatus.ERROR, [], "parse_error", str(exc)

    # Ошибка уровня ответа
    error = root.find(".//response/error")
    if error is not None:
        code = error.get("code")
        message = _text(error)
        if code in _NOT_FOUND_ERROR_CODES:
            return CheckStatus.NOT_FOUND, [], code, message
        if code in _BLOCKING_ERROR_CODES:
            return CheckStatus.BLOCKED, [], code, message
        return CheckStatus.ERROR, [], code, message

    results: list[SerpResult] = []
    for i, doc in enumerate(root.findall(".//results//doc"), start=1):
        url = _text(doc.find("url"))
        if not url:
            continue
        domain = _text(doc.find("domain"))
        title = _text(doc.find("title"))
        passages = doc.find("passages")
        snippet = _text(passages) or _text(doc.find("headline"))
        results.append(
            SerpResult(
                url=url,
                result_type=ResultType.ORGANIC,
                title=title,
                snippet=snippet,
                raw_position=i,
            )
        )

    if not results:
        # Пустой, но валидный ответ трактуем как «не найдено», не как ошибку.
        return CheckStatus.NOT_FOUND, [], None, None
    return CheckStatus.SUCCESS, results, None, None


class YandexApiProvider:
    source = "api"

    def __init__(
        self,
        folder_id: str,
        api_key: str,
        *,
        host: str = "https://yandex.ru/search/xml",
        timeout: float = 30.0,
    ) -> None:
        self.folder_id = folder_id
        self.api_key = api_key
        self.host = host
        self.timeout = timeout

    def _params(self, request: SearchRequest) -> dict[str, str]:
        return {
            "folderid": self.folder_id,
            "apikey": self.api_key,
            "text": request.query,
            "lr": str(request.region_lr),
            "l10n": "ru",
            "groupby": f"attr=d.mode=deep.groups-on-page={min(request.depth, 100)}.docs-in-group=1",
        }

    async def _request(self, request: SearchRequest) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.get(self.host, params=self._params(request))

    async def fetch(self, request: SearchRequest) -> SerpFetch:
        started = time.monotonic()
        try:
            resp = await self._request(request)
        except httpx.HTTPError as exc:
            return SerpFetch(
                status=CheckStatus.ERROR,
                source=self.source,
                error_code="http_error",
                error_message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code != 200:
            status = CheckStatus.BLOCKED if resp.status_code in (403, 429) else CheckStatus.ERROR
            return SerpFetch(
                status=status,
                source=self.source,
                search_url=str(resp.url),
                error_code=f"http_{resp.status_code}",
                error_message=resp.text[:500],
                duration_ms=duration_ms,
            )

        status, results, error_code, error_message = parse_yandex_xml(resp.text)
        return SerpFetch(
            status=status,
            results=results,
            search_url=str(resp.url),
            source=self.source,
            parser_version=PARSER_VERSION,
            error_code=error_code,
            error_message=error_message,
            duration_ms=duration_ms,
        )
