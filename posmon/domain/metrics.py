"""Сводные SEO-метрики по набору позиций (раздел 4 ТЗ v2).

Ключевые правила:
- средняя и медиана считаются ТОЛЬКО по найденным позициям (NULL/NOT_FOUND не
  учитываются как ноль и не как значение глубины);
- вместе со средней ВСЕГДА возвращается coverage — доля запросов, у которых
  вообще есть позиция; без него средняя обманчива (вылет из ТОП-50 «улучшает»
  среднюю).
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

TOP_BUCKETS: tuple[int, ...] = (3, 10, 20, 50)


@dataclass(slots=True)
class PositionMetrics:
    total: int                 # всего позиций в выборке (вкл. не найденные)
    found: int                 # из них найдено (позиция не None)
    coverage: float            # found / total, 0..1
    average: float | None      # средняя по найденным, None если найденных нет
    median: float | None       # медиана по найденным
    top: dict[int, int]        # {3: n, 10: n, 20: n, 50: n} — count(position <= N)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "found": self.found,
            "coverage": round(self.coverage, 4),
            "average": None if self.average is None else round(self.average, 2),
            "median": self.median,
            "top": dict(self.top),
        }


def compute_metrics(
    positions: Iterable[int | None],
    buckets: tuple[int, ...] = TOP_BUCKETS,
) -> PositionMetrics:
    """Посчитать сводные метрики по позициям.

    ``positions`` — позиции по набору запросов (для одного сайта × профиль ×
    период). ``None`` означает «не найден в пределах глубины» и НЕ учитывается
    в средней/медиане, но учитывается в total и, соответственно, в coverage.
    """
    positions = list(positions)
    total = len(positions)
    found_values = [p for p in positions if p is not None]
    found = len(found_values)

    average = (sum(found_values) / found) if found else None
    med = float(median(found_values)) if found else None
    top = {n: sum(1 for p in found_values if p <= n) for n in buckets}
    coverage = (found / total) if total else 0.0

    return PositionMetrics(
        total=total,
        found=found,
        coverage=coverage,
        average=average,
        median=med,
        top=top,
    )
