from posmon.domain.position import compute_position
from posmon.domain.results import CheckStatus, ResultType
from posmon.providers.yandex_api import parse_yandex_xml

XML_OK = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
 <response>
  <results>
   <grouping>
    <group><doc>
      <url>https://site-a.ru/page</url>
      <domain>site-a.ru</domain>
      <title>Site <hlword>A</hlword> ресторан</title>
      <passages><passage>Описание А</passage></passages>
    </doc></group>
    <group><doc>
      <url>https://ekb-guide.ru/article</url>
      <domain>ekb-guide.ru</domain>
      <title>ЕКБ ГИД</title>
    </doc></group>
   </grouping>
  </results>
 </response>
</yandexsearch>"""

XML_LIMIT = '<yandexsearch><response><error code="55">Too many</error></response></yandexsearch>'
XML_NOTHING = '<yandexsearch><response><error code="15">Ничего не найдено</error></response></yandexsearch>'
XML_BROKEN = "<yandexsearch><response><not-closed>"


def test_parse_ok_results_and_order():
    status, results, code, msg = parse_yandex_xml(XML_OK)
    assert status == CheckStatus.SUCCESS
    assert len(results) == 2
    assert results[0].url == "https://site-a.ru/page"
    assert results[0].result_type == ResultType.ORGANIC
    assert results[0].title == "Site A ресторан"      # теги склеены
    assert results[0].snippet == "Описание А"
    assert results[0].raw_position == 1
    # позиция вычисляется поверх распарсенной выдачи
    assert compute_position(results, "ekb-guide.ru") == 2


def test_parse_limit_is_blocked():
    status, results, code, msg = parse_yandex_xml(XML_LIMIT)
    assert status == CheckStatus.BLOCKED
    assert code == "55"
    assert results == []


def test_parse_nothing_found_is_not_found_not_error():
    status, results, code, msg = parse_yandex_xml(XML_NOTHING)
    assert status == CheckStatus.NOT_FOUND
    assert code == "15"


def test_parse_broken_xml_is_error():
    status, results, code, msg = parse_yandex_xml(XML_BROKEN)
    assert status == CheckStatus.ERROR
    assert code == "parse_error"


def test_parse_v2_response_base64_rawdata():
    import base64

    from posmon.providers.yandex_api import parse_v2_response

    data = {"rawData": base64.b64encode(XML_OK.encode("utf-8")).decode("ascii")}
    status, results, code, msg = parse_v2_response(data)
    assert status == CheckStatus.SUCCESS
    assert len(results) == 2


def test_parse_v2_response_missing_rawdata_is_error():
    from posmon.providers.yandex_api import parse_v2_response

    status, results, code, msg = parse_v2_response({"foo": "bar"})
    assert status == CheckStatus.ERROR
    assert code == "no_rawdata"
