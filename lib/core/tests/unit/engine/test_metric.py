"""Unit tests for checking a metric's type against its declared range."""

import pytest

from qbrixcore.engine import EngineError
from qbrixcore.engine import MetricType
from qbrixcore.engine import ScoreRange
from qbrixcore.engine import check_metric


@pytest.mark.parametrize("metric_type", ["conversion", "count", "value"])
def test_accepts_a_type_without_a_range(metric_type):
    assert check_metric(metric_type, None) is MetricType(metric_type)


def test_accepts_a_score_with_its_range():
    assert check_metric("score", ScoreRange(1.0, 5.0)) is MetricType.SCORE


def test_refuses_an_unknown_type():
    with pytest.raises(EngineError, match="unknown metric type 'revenue'"):
        check_metric("revenue", None)


def test_refuses_a_score_without_a_range():
    with pytest.raises(EngineError, match="a score metric needs its declared range"):
        check_metric(MetricType.SCORE, None)


def test_refuses_a_range_on_another_type():
    with pytest.raises(EngineError, match="a value metric has no range"):
        check_metric(MetricType.VALUE, ScoreRange(0.0, 1.0))
