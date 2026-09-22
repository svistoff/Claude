from posmon.domain.metrics import compute_metrics


class TestComputeMetrics:
    def test_average_and_median_ignore_none(self):
        m = compute_metrics([1, 3, 5, None])
        assert m.total == 4
        assert m.found == 3
        assert m.average == 3.0          # (1+3+5)/3, None не учитывается
        assert m.median == 3.0

    def test_coverage(self):
        m = compute_metrics([1, None, None, None])
        assert m.coverage == 0.25

    def test_top_buckets(self):
        m = compute_metrics([1, 3, 4, 10, 25, 60, None])
        assert m.top[3] == 2    # 1, 3
        assert m.top[10] == 4   # 1, 3, 4, 10
        assert m.top[20] == 4
        assert m.top[50] == 5   # + 25

    def test_none_over_60_not_in_top50(self):
        # позиция 60 найдена, но > 50 -> не входит в ТОП-50
        m = compute_metrics([60])
        assert m.top[50] == 0
        assert m.found == 1

    def test_all_none(self):
        m = compute_metrics([None, None])
        assert m.average is None
        assert m.median is None
        assert m.coverage == 0.0
        assert m.top[10] == 0

    def test_empty(self):
        m = compute_metrics([])
        assert m.total == 0
        assert m.coverage == 0.0
        assert m.average is None

    def test_as_dict_rounds(self):
        m = compute_metrics([1, 2, 2])
        d = m.as_dict()
        assert d["average"] == 1.67
        assert d["coverage"] == 1.0
