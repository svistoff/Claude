"""Оценка стоимости по реальным тарифам DeepSeek (раздел 27 ТЗ).

Тарифы пер-модельно (config.yaml → pricing.models), с учётом пиковых часов (×2).
Ничего не захардкожено — всё из конфигурации.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import get_app_config
from .runtime import Usage


def _is_peak(now: datetime, windows: list[list[int]]) -> bool:
    # Пик только пн–пт (0=пн … 4=пт).
    if now.weekday() >= 5:
        return False
    h = now.hour
    return any(a <= h < b for a, b in windows)


def estimate_cost(usage: Usage) -> dict:
    from ..settings_store import current_model

    pricing = get_app_config().pricing
    model = current_model()
    rates = pricing.models.get(model, pricing.default)

    now = datetime.now(timezone.utc)
    peak = _is_peak(now, pricing.peak_windows_utc)
    mult = pricing.peak_multiplier if peak else 1.0

    per_m = 1_000_000
    cache_hit = usage.cache_hit_tokens
    fresh_input = max(usage.input_tokens - cache_hit, 0)

    cost = (
        fresh_input / per_m * rates.get("input", 0.0)
        + cache_hit / per_m * rates.get("input_cache_hit", rates.get("input", 0.0))
        + usage.output_tokens / per_m * rates.get("output", 0.0)
    ) * mult

    return {
        "currency": pricing.currency,
        "model": model,
        "peak": peak,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_hit_tokens": cache_hit,
        "estimated_cost": round(cost, 6),
    }
