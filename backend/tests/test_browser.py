"""Тесты браузер-агента: права на опасные действия + реальный smoke Playwright."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agent import permissions
from app.config import AppConfig, BrowserConfig

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def test_browser_danger_confirm():
    cfg = AppConfig()
    d = permissions.classify("browser", {"action": "click", "text": "Удалить аккаунт"}, cfg)
    assert d.action == permissions.CONFIRM


def test_browser_safe_allow():
    cfg = AppConfig()
    for a in ({"action": "open", "url": "https://x"}, {"action": "get_text"},
              {"action": "click", "text": "Войти"}):
        assert permissions.classify("browser", a, cfg).action == permissions.ALLOW


@pytest.mark.skipif(not os.path.exists(CHROME), reason="chromium недоступен")
def test_browser_smoke(tmp_path: Path, monkeypatch):
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright не установлен")

    import app.browser as bmod

    class FakeSettings:
        browser_executable_path = CHROME
        workspace_tmp = str(tmp_path)

    class FakeApp:
        browser = BrowserConfig()
    monkeypatch.setattr(bmod, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(bmod, "get_app_config", lambda: FakeApp())

    bm = bmod.BrowserManager()
    try:
        r = bm.execute("open", {"url": "data:text/html,<h1>Привет</h1><p>Мир webhook</p>"})
        assert r["ok"], r
        t = bm.execute("get_text", {})
        assert t["ok"] and "webhook" in t["text"]
        s = bm.execute("screenshot", {})
        assert s["ok"] and Path(s["path"]).is_file()
    finally:
        bm.shutdown()
