from datetime import date

from posmon.web.charts import ChartOptions, Series, line_chart


def test_empty_series_renders_placeholder():
    svg = line_chart([])
    assert "<svg" in svg
    assert "Данные отсутствуют" in svg


def test_single_series_renders_polyline_and_markers():
    s = Series(label="Desktop", points=[(date(2026, 9, 1), 5), (date(2026, 9, 2), 3)])
    svg = line_chart([s], ChartOptions(y_max=50))
    assert "<polyline" in svg
    assert "<circle" in svg
    assert "Desktop" in svg  # прямая подпись серии


def test_gap_on_none_breaks_line():
    # None в середине -> два отдельных polyline-сегмента
    s = Series(label="A", points=[(date(2026, 9, 1), 5), (date(2026, 9, 2), None), (date(2026, 9, 3), 4)])
    svg = line_chart([s])
    assert svg.count("<polyline") == 2


def test_inverted_axis_top_is_position_one():
    # позиция 1 должна оказаться выше (меньший y), чем позиция 50
    s1 = Series(label="top", points=[(date(2026, 9, 1), 1)])
    s50 = Series(label="bot", points=[(date(2026, 9, 1), 50)])
    y1 = float(line_chart([s1]).split('cy="')[1].split('"')[0])
    y50 = float(line_chart([s50]).split('cy="')[1].split('"')[0])
    assert y1 < y50
