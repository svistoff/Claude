from posmon.domain.position import (
    compute_position,
    compute_visual_position,
    count_ads_above,
    match_site,
)
from posmon.domain.results import ResultType, SerpResult


def _battle_serp():
    """Дневная боевая выдача: 2 рекламы сверху, колдунщик, потом органика."""
    return [
        SerpResult("https://ad1.ru", ResultType.AD_TOP),      # реклама
        SerpResult("https://ad2.ru", ResultType.AD_TOP),      # реклама
        SerpResult("https://biz.ru", ResultType.BUSINESS),    # колдунщик
        SerpResult("https://site-a.ru", ResultType.ORGANIC),  # органика #1, визуально 4-й блок
        SerpResult("https://site-b.ru", ResultType.ORGANIC),  # органика #2, визуально 5-й
    ]


class TestVisualPosition:
    def test_organic_position_ignores_ads(self):
        assert compute_position(_battle_serp(), "site-a.ru") == 1

    def test_visual_counts_all_blocks_above(self):
        # site-a органически #1, но на странице это 4-й блок (2 рекламы + колдунщик)
        assert compute_visual_position(_battle_serp(), "site-a.ru") == 4
        assert compute_visual_position(_battle_serp(), "site-b.ru") == 5

    def test_ads_above(self):
        assert count_ads_above(_battle_serp(), "site-a.ru") == 2
        assert count_ads_above(_battle_serp(), "site-b.ru") == 2

    def test_not_found_returns_none(self):
        assert compute_visual_position(_battle_serp(), "missing.ru") is None
        assert count_ads_above(_battle_serp(), "missing.ru") is None

    def test_no_ads_visual_equals_organic(self):
        serp = [SerpResult("https://x.ru", ResultType.ORGANIC),
                SerpResult("https://site-a.ru", ResultType.ORGANIC)]
        assert compute_visual_position(serp, "site-a.ru") == 2
        assert compute_position(serp, "site-a.ru") == 2
        assert count_ads_above(serp, "site-a.ru") == 0


class TestMatchSiteVisual:
    def test_with_visual_flag(self):
        m = match_site(_battle_serp(), "site-a.ru", with_visual=True)
        assert m.position == 1
        assert m.visual_position == 4
        assert m.ads_above == 2

    def test_without_visual_flag_leaves_none(self):
        m = match_site(_battle_serp(), "site-a.ru")
        assert m.position == 1
        assert m.visual_position is None
        assert m.ads_above is None
