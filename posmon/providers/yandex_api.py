"""Провайдер Yandex Search API v2 (Yandex AI Studio / Cloud).

Синхронный веб-поиск: POST на v2-эндпоинт с заголовком ``Authorization: Api-Key``
и телом с ``folderId``. Ответ содержит ``rawData`` — base64 с XML в том же
формате, что и классический XML API, поэтому парсер :func:`parse_yandex_xml`
переиспользуется как есть.

Реклама и колдунщики через API обычно не отдаются, поэтому результаты
размечаются как ``organic``.

ВАЖНО: точные имена полей v2 подтверждаются на первом живом запросе — при
расхождении сервер вернёт 400 с описанием, и подгонка займёт пару минут. HTTP
вынесен в :meth:`_request`, парсинг ответа — в :func:`parse_v2_response`.
"""
from __future__ import annotations

import base64
import time
from xml.etree import ElementTree as ET

import httpx

from ..domain.results import CheckStatus, ResultType, SerpResult
from .base import SearchRequest, SerpFetch

PARSER_VERSION = "yandex-xml-1"
DEFAULT_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/web/search"

_BLOCKING_ERROR_CODES = {"55"}       # 55 = превышен лимит запросов
_NOT_FOUND_ERROR_CODES = {"15"}      # 15 = искомая комбинация слов нигде не встречается
_TEMP_ERROR_CODES = {"1", "10", "100", "111"}


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    text = "".join(el.itertext()).strip()
    return text or None


def parse_yandex_xml(xml_text: str) -> tuple[CheckStatus, list[SerpResult], str | None, str | None]:
    """Разобрать XML-ответ Yandex Search API (формат yandexsearch).

    Возвращает ``(status, results, error_code, error_message)``.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return CheckStatus.ERROR, [], "parse_error", str(exc)

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
        return CheckStatus.NOT_FOUND, [], None, None
    return CheckStatus.SUCCESS, results, None, None


def parse_v2_response(data: dict) -> tuple[CheckStatus, list[SerpResult], str | None, str | None]:
    """Извлечь и разобрать выдачу из JSON-ответа v2 (поле ``rawData`` — base64 XML)."""
    raw = data.get("rawData") or data.get("raw_data")
    if not raw:
        # v2 может обернуть результат в operation.response — попробуем достать
        response = data.get("response") if isinstance(data.get("response"), dict) else None
        if response:
            raw = response.get("rawData") or response.get("raw_data")
    if not raw:
        return CheckStatus.ERROR, [], "no_rawdata", f"нет rawData в ответе: {list(data)[:6]}"
    try:
        xml_text = base64.b64decode(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        return CheckStatus.ERROR, [], "b64_decode", str(exc)
    return parse_yandex_xml(xml_text)


class YandexApiProvider:
    source = "api"

    def __init__(
        self,
        folder_id: str,
        api_key: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        region_lr: int = 54,
        timeout: float = 40.0,
    ) -> None:
        self.folder_id = folder_id
        self.api_key = api_key
        self.endpoint = endpoint or DEFAULT_ENDPOINT
        self.region_lr = region_lr
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }

    def _body(self, request: SearchRequest) -> dict:
        return {
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": request.query,
                "familyMode": "FAMILY_MODE_NONE",
                "page": "0",
            },
            "groupSpec": {
                "groupMode": "GROUP_MODE_FLAT",
                "groupsOnPage": str(min(request.depth, 100)),
                "docsInGroup": "1",
            },
            "region": str(request.region_lr or self.region_lr),
            "l10n": "LOCALIZATION_RU",
            "folderId": self.folder_id,
            "responseFormat": "FORMAT_XML",
        }

    async def _request(self, request: SearchRequest) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(self.endpoint, headers=self._headers(), json=self._body(request))

    async def fetch(self, request: SearchRequest) -> SerpFetch:
        started = time.monotonic()
        try:
            resp = await self._request(request)
        except httpx.HTTPError as exc:
            return SerpFetch(
                status=CheckStatus.ERROR, source=self.source,
                error_code="http_error", error_message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code != 200:
            status = CheckStatus.BLOCKED if resp.status_code in (403, 429) else CheckStatus.ERROR
            return SerpFetch(
                status=status, source=self.source, search_url=str(resp.url),
                error_code=f"http_{resp.status_code}", error_message=resp.text[:500],
                duration_ms=duration_ms,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            return SerpFetch(
                status=CheckStatus.ERROR, source=self.source,
                error_code="bad_json", error_message=str(exc), duration_ms=duration_ms,
            )

        status, results, error_code, error_message = parse_v2_response(data)
        return SerpFetch(
            status=status, results=results, search_url=str(resp.url),
            source=self.source, parser_version=PARSER_VERSION,
            error_code=error_code, error_message=error_message, duration_ms=duration_ms,
        )
