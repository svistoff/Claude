"""Тесты оценки стоимости: пер-модельные тарифы и пиковые часы."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agent import pricing
from app.agent.runtime import Usage
from app.config import PricingConfig


def test_is_peak_windows():
    windows = [[1, 4], [6, 10]]
    # вторник 07:00 UTC — пик
    assert pricing._is_peak(datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc), windows)
    # вторник 12:00 UTC — off-peak
    assert not pricing._is_peak(datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc), windows)
    # суббота 07:00 — off-peak (выходной)
    assert not pricing._is_peak(datetime(2026, 9, 19, 7, 0, tzinfo=timezone.utc), windows)


def test_cost_uses_model_rates(monkeypatch):
    cfg = PricingConfig(models={
        "deepseek-flash": {"input": 0.15, "input_cache_hit": 0.003, "output": 0.60},
        "deepseek-v4-pro": {"input": 0.66, "input_cache_hit": 0.022, "output": 1.98},
    }, peak_windows_utc=[[1, 4]])

    class FakeApp:
        pricing = cfg
    monkeypatch.setattr(pricing, "get_app_config", lambda: FakeApp)
    monkeypatch.setattr("app.settings_store.current_model", lambda: "deepseek-flash")
    # off-peak: 1M output flash = $0.60
    u = Usage(input_tokens=0, output_tokens=1_000_000, cache_hit_tokens=0)
    monkeypatch.setattr(pricing, "_is_peak", lambda now, w: False)
    r = pricing.estimate_cost(u)
    assert r["model"] == "deepseek-flash"
    assert abs(r["estimated_cost"] - 0.60) < 1e-6

    monkeypatch.setattr("app.settings_store.current_model", lambda: "deepseek-v4-pro")
    r2 = pricing.estimate_cost(u)
    assert abs(r2["estimated_cost"] - 1.98) < 1e-6


def test_peak_doubles(monkeypatch):
    cfg = PricingConfig(models={"deepseek-flash": {"input": 0.15, "input_cache_hit": 0.003, "output": 0.60}},
                        peak_multiplier=2.0)

    class FakeApp:
        pricing = cfg
    monkeypatch.setattr(pricing, "get_app_config", lambda: FakeApp)
    monkeypatch.setattr("app.settings_store.current_model", lambda: "deepseek-flash")
    monkeypatch.setattr(pricing, "_is_peak", lambda now, w: True)
    u = Usage(input_tokens=0, output_tokens=1_000_000, cache_hit_tokens=0)
    r = pricing.estimate_cost(u)
    assert r["peak"] is True
    assert abs(r["estimated_cost"] - 1.20) < 1e-6
