from posmon.domain.normalize import MATCH_EXACT_HOST
from posmon.domain.position import (
    compute_business_position,
    compute_position,
    match_site,
)
from posmon.domain.results import ResultType, SerpResult


def _r(url, rt=ResultType.ORGANIC):
    return SerpResult(url=url, result_type=rt)


def _sample_serp():
    """Выдача: реклама и колдунщики перемешаны с органикой."""
    return [
        _r("https://ad.ru/x", ResultType.AD_TOP),          # реклама — не слот
        _r("https://biz1.ru", ResultType.BUSINESS),         # блок Бизнеса — не слот
        _r("https://biz2.ru", ResultType.BUSINESS),
        _r("https://site-a.ru/page"),                        # органика #1
        _r("https://site-b.ru/page"),                        # органика #2
        _r("https://maps.ru", ResultType.MAPS),              # колдунщик — не слот
        _r("https://site-c.ru/page"),                        # органика #3
        _r("https://ekb-guide.ru/article"),                 # органика #4
        _r("https://site-a.ru/other"),                       # дубль site-a, органика #5
        _r("https://adbottom.ru", ResultType.AD_BOTTOM),
    ]


class TestComputePosition:
    def test_ads_and_kolduns_do_not_take_slots(self):
        # ekb-guide стоит физически 8-м в полной выдаче, но органически он #4
        assert compute_position(_sample_serp(), "ekb-guide.ru") == 4

    def test_first_organic_is_one(self):
        assert compute_position(_sample_serp(), "site-a.ru") == 1

    def test_duplicate_domain_takes_best_position(self):
        # site-a встречается в органике на #1 и #5 -> берём лучшую (#1)
        assert compute_position(_sample_serp(), "site-a.ru") == 1

    def test_not_found_returns_none(self):
        assert compute_position(_sample_serp(), "missing.ru") is None

    def test_business_domain_not_counted_as_organic(self):
        # biz1.ru есть только в блоке Бизнеса -> органической позиции нет
        assert compute_position(_sample_serp(), "biz1.ru") is None

    def test_subdomain_matches_in_domain_mode(self):
        serp = [_r("https://blog.site-x.ru")]
        assert compute_position(serp, "site-x.ru") == 1

    def test_exact_host_mode(self):
        serp = [_r("https://blog.site-x.ru"), _r("https://www.site-x.ru")]
        assert compute_position(serp, "www.site-x.ru", MATCH_EXACT_HOST) == 2


class TestBusinessPosition:
    def test_business_block_ranked_separately(self):
        assert compute_business_position(_sample_serp(), "biz2.ru") == 2

    def test_organic_domain_has_no_business_position(self):
        assert compute_business_position(_sample_serp(), "site-a.ru") is None


class TestMatchSite:
    def test_combined(self):
        m = match_site(_sample_serp(), "site-c.ru", with_business=True)
        assert m.position == 3
        assert m.business_position is None
        assert m.found is True

    def test_not_found(self):
        m = match_site(_sample_serp(), "nowhere.ru")
        assert m.position is None
        assert m.found is False

    def test_accepts_generator(self):
        gen = (r for r in _sample_serp())
        m = match_site(gen, "site-b.ru", with_business=True)
        assert m.position == 2
