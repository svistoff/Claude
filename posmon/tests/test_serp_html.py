from posmon.domain.position import compute_position, compute_visual_position, count_ads_above
from posmon.domain.results import ResultType
from posmon.providers.serp_html import parse_serp_html

# Синтетическая выдача в структуре, близкой к десктопному Яндексу:
# реклама сверху -> органика -> блок Бизнеса -> органика.
SERP = """
<ul>
  <li class="serp-item serp-adv-item">
    <span class="Label">Реклама</span>
    <a class="Link OrganicTitle-Link" href="https://ad-a.ru/x">Реклама А</a>
  </li>
  <li class="serp-item">
    <a class="OrganicTitle-Link" href="https://site-a.ru/page">Site A</a>
  </li>
  <li class="serp-item Companies">
    <a class="Link" href="https://yandex.ru/maps/org/1">Организация</a>
  </li>
  <li class="serp-item">
    <a class="OrganicTitle-Link" href="https://site-b.ru/page">Site B</a>
  </li>
  <li class="serp-item">
    <div class="no-link-service-block">без ссылки</div>
  </li>
</ul>
"""


def test_parse_classifies_and_orders():
    results = parse_serp_html(SERP)
    types = [(r.result_type, r.host) for r in results]
    assert types == [
        (ResultType.AD_TOP, "ad-a.ru"),
        (ResultType.ORGANIC, "site-a.ru"),
        (ResultType.BUSINESS, "yandex.ru"),
        (ResultType.ORGANIC, "site-b.ru"),
    ]
    # служебный блок без ссылки пропущен
    assert len(results) == 4


def test_positions_over_parsed_serp():
    results = parse_serp_html(SERP)
    # органика: site-a #1, site-b #2 (реклама и Бизнес не в счёт)
    assert compute_position(results, "site-a.ru") == 1
    assert compute_position(results, "site-b.ru") == 2
    # боевая: site-a — 2-й блок на странице (над ним 1 реклама)
    assert compute_visual_position(results, "site-a.ru") == 2
    assert count_ads_above(results, "site-a.ru") == 1


def test_empty_html():
    assert parse_serp_html("") == []
