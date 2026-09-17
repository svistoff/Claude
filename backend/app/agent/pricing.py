"""Оценка стоимости по тарифам DeepSeek из config.yaml (раздел 27 ТЗ).

Тарифы не захардкожены — берутся из pricing.per_million_tokens.
"""

from __future__ import annotations

from ..config import get_app_config
from .runtime import Usage


def estimate_cost(usage: Usage) -> dict:
    pricing = get_app_config().pricing
    rates = pricing.per_million_tokens
    per_m = 1_000_000

    # Кэшированные входные токены тарифицируются по льготной ставке.
    cache_hit = usage.cache_hit_tokens
    fresh_input = max(usage.input_tokens - cache_hit, 0)

    cost = (
        fresh_input / per_m * rates.get("input", 0.0)
        + cache_hit / per_m * rates.get("input_cache_hit", rates.get("input", 0.0))
        + usage.output_tokens / per_m * rates.get("output", 0.0)
    )
    return {
        "currency": pricing.currency,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_hit_tokens": cache_hit,
        "estimated_cost": round(cost, 6),
    }
