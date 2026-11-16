from posmon.domain.position import match_site
from posmon.domain.results import CheckStatus
from posmon.providers.base import SearchRequest
from posmon.providers.mock import MockProvider, sample_serp


async def test_mock_success_and_position():
    provider = MockProvider(default_serp=sample_serp())
    fetch = await provider.fetch(SearchRequest(query="ресторан Екатеринбург"))
    assert fetch.status == CheckStatus.SUCCESS
    assert fetch.ok is True
    # ekb-guide органически второй (site-a #1, ekb-guide #2)
    assert match_site(fetch.results, "ekb-guide.ru").position == 2


async def test_mock_forced_error_is_not_ok():
    provider = MockProvider(force_status=CheckStatus.CAPTCHA)
    fetch = await provider.fetch(SearchRequest(query="x"))
    assert fetch.status == CheckStatus.CAPTCHA
    assert fetch.ok is False
    assert fetch.results == []


async def test_mock_per_query_serp():
    from posmon.domain.results import ResultType, SerpResult

    provider = MockProvider(
        serp_by_query={"бар": [SerpResult("https://bar.ru", ResultType.ORGANIC)]},
        default_serp=sample_serp(),
    )
    fetch = await provider.fetch(SearchRequest(query="бар"))
    assert match_site(fetch.results, "bar.ru").position == 1
