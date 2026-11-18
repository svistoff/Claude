"""Тесты инструментов веб-поиска и чтения страниц (DeepSeek Search & Fetch API).

HTTP — мок: реальные запросы к DeepSeek не делаются (стоят $0.75/1000).
"""

from __future__ import annotations

from pathlib import Path

from app.config import AppConfig
from app.tools import web
from app.tools.base import ToolContext
from app.tools.registry import _DISPATCH, TOOL_SCHEMAS


def _ctx(root: Path) -> ToolContext:
    return ToolContext(project_name="test", project_root=root, config=AppConfig())


class _Resp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class _Client:
    """Мок httpx.Client: запоминает payload, отдаёт заранее заданный ответ."""

    calls: list[dict] = []
    response: _Resp = _Resp()

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        _Client.calls.append({"url": url, "headers": headers, "json": json})
        return _Client.response


def _settings(key: str = "k"):
    return type("S", (), {"deepseek_api_key": key})()


SEARCH_JSON = {
    "results": [
        {
            "rerank_score": 2.4,
            "title": "Авиабилеты Москва — Сочи",
            "url": "https://example.com/tickets",
            "snippet": "Цены от 6 400 ₽",
            "summary": "Самый дешёвый билет на 12 декабря стоит 6 400 ₽ с багажом.",
            "content": "",
            "site_name": "Example Travel",
            "date": "2026-12-01T00:00:00+00:00",
        },
        {
            "title": "Второй результат",
            "url": "https://example.org/page",
            "summary": "Другое предложение за 7 100 ₽.",
            "site_name": None,
            "date": None,
        },
    ]
}


# --- Регистрация в реестре ----------------------------------------------------

def test_schemas_and_dispatch_registered():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert {"web_search", "web_fetch"} <= names
    assert {"web_search", "web_fetch"} <= set(_DISPATCH)


# --- web_search ---------------------------------------------------------------

def test_search_without_key(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "get_settings", lambda: _settings(""))
    r = web.web_search(_ctx(tmp_path), "билеты")
    assert not r.ok and "DEEPSEEK_API_KEY" in r.content


def test_search_empty_query(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "get_settings", _settings)
    r = web.web_search(_ctx(tmp_path), "   ")
    assert not r.ok and "Пустой" in r.content


def test_search_disabled_in_config(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "get_settings", _settings)
    cfg = AppConfig()
    cfg.web.enabled = False
    monkeypatch.setattr(web, "get_app_config", lambda: cfg)
    r = web.web_search(_ctx(tmp_path), "кот")
    assert not r.ok and "выключен" in r.content


def test_search_success_formats_results(monkeypatch, tmp_path):
    _Client.calls = []
    _Client.response = _Resp(200, SEARCH_JSON)
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)

    r = web.web_search(_ctx(tmp_path), "билеты Москва Сочи", count=3, ori_question="сколько лететь")

    assert r.ok, r.content
    # Запрос ушёл на нужный endpoint с count и ori_question.
    call = _Client.calls[0]
    assert call["url"].endswith("/v1/tools/search")
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["json"] == {"query": "билеты Москва Сочи", "count": 3,
                            "ori_question": "сколько лететь"}
    # Модели отданы заголовки, ссылки, дата и summary.
    assert "Авиабилеты Москва — Сочи" in r.content
    assert "https://example.com/tickets" in r.content
    assert "6 400" in r.content
    assert "2026-12-01" in r.content
    assert len(r.extra["results"]) == 2
    # Подсказка про следующий шаг.
    assert "web_fetch" in r.content


def test_search_count_clamped_to_api_limit(monkeypatch, tmp_path):
    _Client.calls = []
    _Client.response = _Resp(200, SEARCH_JSON)
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)
    web.web_search(_ctx(tmp_path), "кот", count=999)
    assert _Client.calls[0]["json"]["count"] == 50


def test_search_long_query_truncated_to_128(monkeypatch, tmp_path):
    _Client.calls = []
    _Client.response = _Resp(200, SEARCH_JSON)
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)
    web.web_search(_ctx(tmp_path), "я" * 300)
    assert len(_Client.calls[0]["json"]["query"]) == 128


def test_search_need_content_passed(monkeypatch, tmp_path):
    _Client.calls = []
    _Client.response = _Resp(200, SEARCH_JSON)
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)
    web.web_search(_ctx(tmp_path), "кот", need_content=True)
    assert _Client.calls[0]["json"]["need_content"] is True


def test_search_empty_results_is_not_error(monkeypatch, tmp_path):
    _Client.response = _Resp(200, {"results": []})
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)
    r = web.web_search(_ctx(tmp_path), "абракадабра")
    assert r.ok and "ничего не найдено" in r.content


def test_search_error_status_surfaced(monkeypatch, tmp_path):
    _Client.response = _Resp(402, {"error": {"message": "Insufficient balance"}}, text="")
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)
    r = web.web_search(_ctx(tmp_path), "кот")
    assert not r.ok
    assert "402" in r.content and "баланс" in r.content.lower()


def test_search_network_error(monkeypatch, tmp_path):
    class _BoomClient(_Client):
        def post(self, url, headers=None, json=None):
            raise web.httpx.ConnectError("nope")

    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _BoomClient)
    r = web.web_search(_ctx(tmp_path), "кот")
    assert not r.ok and "Сетевая ошибка" in r.content


# --- web_fetch ----------------------------------------------------------------

def test_fetch_requires_http_url(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "get_settings", _settings)
    r = web.web_fetch(_ctx(tmp_path), "example.com/page")
    assert not r.ok and "http" in r.content


def test_fetch_success_returns_markdown(monkeypatch, tmp_path):
    _Client.calls = []
    _Client.response = _Resp(200, {"title": "Статья", "content": "# Заголовок\n\nТекст статьи."})
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)

    r = web.web_fetch(_ctx(tmp_path), "https://example.com/a")

    assert r.ok, r.content
    assert _Client.calls[0]["url"].endswith("/v1/tools/fetch")
    assert _Client.calls[0]["json"] == {"url": "https://example.com/a"}
    assert "Статья" in r.content and "Текст статьи." in r.content
    assert r.extra["truncated"] is False


def test_fetch_truncates_long_page(monkeypatch, tmp_path):
    _Client.response = _Resp(200, {"title": "", "content": "x" * 5000})
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)
    r = web.web_fetch(_ctx(tmp_path), "https://example.com/big", max_chars=1000)
    assert r.ok
    assert r.extra["truncated"] is True
    assert "обрезано" in r.content
    assert len(r.content) < 1400


def test_fetch_empty_content_is_error(monkeypatch, tmp_path):
    _Client.response = _Resp(200, {"title": "Пусто", "content": ""})
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)
    r = web.web_fetch(_ctx(tmp_path), "https://example.com/empty")
    assert not r.ok and "не содержит" in r.content


def test_fetch_404_explained(monkeypatch, tmp_path):
    _Client.response = _Resp(404, {"error": {"message": "no content"}}, text="")
    monkeypatch.setattr(web, "get_settings", _settings)
    monkeypatch.setattr(web.httpx, "Client", _Client)
    r = web.web_fetch(_ctx(tmp_path), "https://example.com/missing")
    assert not r.ok and "404" in r.content
