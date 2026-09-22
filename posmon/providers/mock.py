"""Детерминированный мок-провайдер для тестов и локальной разработки."""
from __future__ import annotations

from ..domain.results import CheckStatus, SerpResult
from .base import SearchRequest, SerpFetch


class MockProvider:
    """Возвращает заранее заданную выдачу.

    ``serp_by_query`` — карта {запрос: список SerpResult}. Если запроса нет в
    карте, используется ``default_serp``. ``force_status`` позволяет имитировать
    ошибку/капчу/блокировку.
    """

    source = "mock"

    def __init__(
        self,
        serp_by_query: dict[str, list[SerpResult]] | None = None,
        default_serp: list[SerpResult] | None = None,
        force_status: CheckStatus | None = None,
    ) -> None:
        self.serp_by_query = serp_by_query or {}
        self.default_serp = default_serp or []
        self.force_status = force_status

    async def fetch(self, request: SearchRequest) -> SerpFetch:
        if self.force_status is not None and self.force_status not in (
            CheckStatus.SUCCESS,
            CheckStatus.NOT_FOUND,
        ):
            return SerpFetch(
                status=self.force_status,
                source=self.source,
                error_code=self.force_status.value,
                error_message="mock forced status",
            )
        results = self.serp_by_query.get(request.query, self.default_serp)
        return SerpFetch(
            status=CheckStatus.SUCCESS,
            results=list(results),
            search_url=f"mock://yandex/search?text={request.query}&lr={request.region_lr}",
            source=self.source,
            parser_version="mock-1",
            duration_ms=1,
        )


def sample_serp() -> list[SerpResult]:
    """Небольшая реалистичная выдача для разработки."""
    from ..domain.results import ResultType

    return [
        SerpResult("https://ad.example/x", ResultType.AD_TOP, raw_position=1),
        SerpResult("https://biz.example", ResultType.BUSINESS, title="Организация", raw_position=2),
        SerpResult("https://site-a.ru/", ResultType.ORGANIC, title="Site A", raw_position=3),
        SerpResult("https://ekb-guide.ru/", ResultType.ORGANIC, title="ЕКБ ГИД", raw_position=4),
        SerpResult("https://site-b.ru/", ResultType.ORGANIC, title="Site B", raw_position=5),
    ]
