"""Серверный рендер SVG-графиков (без JS-зависимостей).

График истории позиции: ось Y инвертирована (позиция 1 сверху), чтобы движение
линии вверх означало улучшение (раздел 19.1 ТЗ). Одна серия — без легенды
(заголовок называет её), несколько — с легендой и прямыми подписями.

Палитра категориальных серий взята из валидированного набора (dark-режим).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html import escape

# Валидированный категориальный порядок (dark-шаги), до 5 профилей.
SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]

# Цвета сетки/осей/подписей — через CSS-переменные (тема light/dark из style.css).
_GRID = "var(--chart-grid, #d7dbe0)"
_AXIS = "var(--chart-axis, #9aa2ac)"
_INK = "var(--chart-ink, #52514e)"


@dataclass(slots=True)
class Series:
    label: str
    points: list[tuple[date, int | None]]  # (дата, позиция|None) в порядке дат
    color: str = SERIES_COLORS[0]


@dataclass(slots=True)
class ChartOptions:
    width: int = 720
    height: int = 300
    pad_left: int = 40
    pad_right: int = 90
    pad_top: int = 16
    pad_bottom: int = 34
    y_max: int = 50           # глубина мониторинга (низ шкалы)
    y_ticks: tuple[int, ...] = (1, 10, 20, 30, 40, 50)


def _x_positions(dates: list[date], x0: int, x1: int) -> dict[date, float]:
    if not dates:
        return {}
    if len(dates) == 1:
        return {dates[0]: (x0 + x1) / 2}
    lo = min(d.toordinal() for d in dates)
    hi = max(d.toordinal() for d in dates)
    span = max(1, hi - lo)
    return {d: x0 + (x1 - x0) * (d.toordinal() - lo) / span for d in dates}


def line_chart(series: list[Series], opt: ChartOptions | None = None) -> str:
    """Отрисовать линейный график истории позиций в SVG (строка)."""
    opt = opt or ChartOptions()
    x0, x1 = opt.pad_left, opt.width - opt.pad_right
    y0, y1 = opt.pad_top, opt.height - opt.pad_bottom

    all_dates = sorted({d for s in series for d, _ in s.points})
    if not all_dates:
        return (
            f'<svg viewBox="0 0 {opt.width} {opt.height}" class="chart" '
            f'role="img" aria-label="Нет данных">'
            f'<text x="{opt.width/2}" y="{opt.height/2}" fill="{_AXIS}" '
            f'text-anchor="middle">Данные отсутствуют</text></svg>'
        )

    xpos = _x_positions(all_dates, x0, x1)

    def yv(pos: int) -> float:
        # инверсия: позиция 1 -> верх (y0), y_max -> низ (y1)
        p = min(max(pos, 1), opt.y_max)
        return y0 + (y1 - y0) * (p - 1) / max(1, opt.y_max - 1)

    parts: list[str] = [
        f'<svg viewBox="0 0 {opt.width} {opt.height}" class="chart" '
        f'role="img" aria-label="История позиций">'
    ]

    # Горизонтальная сетка + подписи Y (позиции)
    for tick in opt.y_ticks:
        y = yv(tick)
        parts.append(
            f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x0-8}" y="{y+4:.1f}" fill="{_AXIS}" font-size="11" '
            f'text-anchor="end">{tick}</text>'
        )

    # Подписи X (первая, средняя, последняя дата)
    label_dates = {all_dates[0], all_dates[-1], all_dates[len(all_dates)//2]}
    for d in sorted(label_dates):
        x = xpos[d]
        parts.append(
            f'<text x="{x:.1f}" y="{opt.height-12}" fill="{_AXIS}" font-size="11" '
            f'text-anchor="middle">{d.strftime("%d.%m")}</text>'
        )

    # Серии
    for s in series:
        # линия рвётся на пропусках (None) и не-найденных
        segment: list[tuple[float, float]] = []
        segments: list[list[tuple[float, float]]] = []
        for d, pos in s.points:
            if pos is None:
                if segment:
                    segments.append(segment)
                    segment = []
                continue
            segment.append((xpos[d], yv(pos)))
        if segment:
            segments.append(segment)

        for seg in segments:
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in seg)
            parts.append(
                f'<polyline points="{pts}" fill="none" stroke="{s.color}" '
                f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            )
        # маркеры с тултипом
        for d, pos in s.points:
            if pos is None:
                continue
            x, y = xpos[d], yv(pos)
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{s.color}">'
                f'<title>{escape(s.label)} · {d.strftime("%d.%m.%Y")}: #{pos}</title></circle>'
            )
        # прямая подпись серии у последней точки
        last = next(((d, p) for d, p in reversed(s.points) if p is not None), None)
        if last is not None:
            d, pos = last
            x, y = xpos[d], yv(pos)
            parts.append(
                f'<text x="{x+8:.1f}" y="{y+4:.1f}" fill="{_INK}" font-size="11">'
                f'{escape(s.label)}</text>'
            )

    parts.append("</svg>")
    return "".join(parts)


def series_from_history(
    label: str, rows: list[tuple[date, int | None]], color: str
) -> Series:
    return Series(label=label, points=rows, color=color)
