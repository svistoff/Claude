"""Тесты сетевой надёжности провайдера DeepSeek (без реальной сети).

Проверяем: понятный текст ошибки, раздельные таймауты, повтор при обрыве до
первых данных и отсутствие повтора после начала ответа.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.llm import deepseek as ds


def _collect(agen):
    async def run():
        return [ev async for ev in agen]
    return asyncio.run(run())


async def _fake_stream_ok(*a, **k):
    """Успешный поток: один текстовый чанк и usage."""
    yield 'data: {"choices":[{"delta":{"content":"ок"}}]}'
    yield 'data: {"usage":{"prompt_tokens":5,"completion_tokens":1,"prompt_cache_hit_tokens":0}}'
    yield "data: [DONE]"


class _FakeResp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, lines=None, exc=None):
        self._lines = lines or []
        self._exc = exc

    async def __aenter__(self):
        if self._exc:
            raise self._exc
        return _FakeResp(self._lines)

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    """Мок httpx.AsyncClient: сценарий задаётся списком ответов/исключений."""

    script: list = []
    calls: int = 0
    timeouts: list = []

    def __init__(self, *a, timeout=None, **k):
        _FakeClient.timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None, json=None):
        item = _FakeClient.script[_FakeClient.calls]
        _FakeClient.calls += 1
        if isinstance(item, Exception):
            return _FakeStreamCtx(exc=item)
        return _FakeStreamCtx(lines=item)


@pytest.fixture(autouse=True)
def _fast_and_fake(monkeypatch):
    _FakeClient.calls = 0
    _FakeClient.timeouts = []
    monkeypatch.setattr(ds.httpx, "AsyncClient", _FakeClient)
    # Бэкофф не должен тормозить тесты.
    monkeypatch.setattr(ds.asyncio, "sleep", _no_sleep)


async def _no_sleep(_sec):
    return None


def _provider(**kw):
    return ds.DeepSeekProvider(api_key="k", base_url="https://api.deepseek.com/v1",
                               model="deepseek-flash", **kw)


# --- Описание ошибок ---------------------------------------------------------

def test_describe_empty_socket_timeout_is_readable():
    """Пустое сообщение httpx (частый случай) не должно давать «ошибка: »."""
    text = ds.DeepSeekProvider._describe(httpx.ReadTimeout(""))
    assert text.startswith("ReadTimeout")
    assert "таймаут" in text.lower()
    assert text.strip() != "ReadTimeout:"


def test_describe_connect_error_has_hint():
    text = ds.DeepSeekProvider._describe(httpx.ConnectError("getaddrinfo failed"))
    assert "ConnectError" in text and "api.deepseek.com" in text


# --- Таймауты ---------------------------------------------------------------

def test_split_timeouts():
    t = _provider(request_timeout=300, connect_timeout=15)._timeout()
    assert t.connect == 15 and t.read == 300 and t.pool == 15


# --- Успешный поток ----------------------------------------------------------

def test_stream_ok_collects_text_and_usage():
    _FakeClient.script = [[
        'data: {"choices":[{"delta":{"content":"ок"}}]}',
        'data: {"usage":{"prompt_tokens":5,"completion_tokens":1,"prompt_cache_hit_tokens":0}}',
        "data: [DONE]",
    ]]
    events = _collect(_provider().stream([{"role": "user", "content": "привет"}]))
    types = [e["type"] for e in events]
    assert "error" not in types
    assert any(e["type"] == "text" and e["delta"] == "ок" for e in events)
    assert any(e["type"] == "usage" and e["input"] == 5 for e in events)


# --- Повторы ----------------------------------------------------------------

def test_retries_on_connect_error_then_succeeds():
    _FakeClient.script = [
        httpx.ConnectError("boom"),
        ['data: {"choices":[{"delta":{"content":"со второй попытки"}}]}', "data: [DONE]"],
    ]
    events = _collect(_provider(retries=2).stream([{"role": "user", "content": "x"}]))
    types = [e["type"] for e in events]
    assert "retry" in types
    assert "error" not in types
    assert any(e["type"] == "text" for e in events)
    assert _FakeClient.calls == 2


def test_gives_up_after_retries_and_explains():
    _FakeClient.script = [httpx.ReadTimeout("")] * 3
    events = _collect(_provider(retries=2).stream([{"role": "user", "content": "x"}]))
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert "ReadTimeout" in errors[0]["message"]
    assert "таймаут" in errors[0]["message"].lower()
    # 1 попытка + 2 повтора
    assert _FakeClient.calls == 3


def test_no_retry_after_response_started():
    """Если текст уже ушёл пользователю, повторять нельзя — будет дубль."""
    class _PartialResp(_FakeResp):
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"начало ответа"}}]}'
            raise httpx.ReadTimeout("")

    class _PartialCtx:
        async def __aenter__(self):
            return _PartialResp([])

        async def __aexit__(self, *a):
            return False

    class _PartialClient(_FakeClient):
        def stream(self, method, url, headers=None, json=None):
            _FakeClient.calls += 1
            return _PartialCtx()

    _FakeClient.script = [[], [], []]
    import app.llm.deepseek as mod
    orig = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = _PartialClient
    try:
        events = _collect(_provider(retries=2).stream([{"role": "user", "content": "x"}]))
    finally:
        mod.httpx.AsyncClient = orig

    # Один вызов = повтора после начала ответа нет; ошибка объяснена.
    assert _FakeClient.calls == 1
    errs = [e for e in events if e["type"] == "error"]
    assert errs and "ReadTimeout" in errs[0]["message"]
    assert "после начала ответа" in errs[0]["message"]
    assert any(e["type"] == "text" for e in events)


def test_retries_zero_means_single_attempt():
    _FakeClient.script = [httpx.ConnectError("boom")]
    events = _collect(_provider(retries=0).stream([{"role": "user", "content": "x"}]))
    assert _FakeClient.calls == 1
    assert [e["type"] for e in events].count("error") == 1


def test_http_status_error_not_retried():
    """402/429 и прочие HTTP-ошибки повтором не лечатся — сообщаем сразу."""
    class _ErrResp(_FakeResp):
        status_code = 402

        async def aread(self):
            return b'{"error":{"message":"Insufficient balance"}}'

    class _ErrCtx:
        async def __aenter__(self):
            return _ErrResp([])

        async def __aexit__(self, *a):
            return False

    class _ErrClient(_FakeClient):
        def stream(self, method, url, headers=None, json=None):
            _FakeClient.calls += 1
            return _ErrCtx()

    _FakeClient.script = [[], []]
    import app.llm.deepseek as mod
    orig = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = _ErrClient
    try:
        events = _collect(_provider(retries=2).stream([{"role": "user", "content": "x"}]))
    finally:
        mod.httpx.AsyncClient = orig

    errs = [e for e in events if e["type"] == "error"]
    assert len(errs) == 1 and "402" in errs[0]["message"]
    assert _FakeClient.calls == 1
