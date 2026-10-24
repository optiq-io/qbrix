from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from qbrixcore.engine.spec import EngineError


class MetricType(str, Enum):
    """what a loop's outcome values mean; the engine resolves its method from it."""

    CONVERSION = "conversion"
    COUNT = "count"
    VALUE = "value"
    SCORE = "score"


@dataclass(frozen=True)
class ScoreRange:
    """the range a score metric declares."""

    lo: float
    hi: float

    def __post_init__(self):
        if self.lo >= self.hi:
            raise EngineError(
                f"a score range needs lo below hi, got [{self.lo}, {self.hi}]"
            )


def check_metric(
    metric_type: MetricType | str, score_range: ScoreRange | None
) -> MetricType:
    """the metric type, refused unless it is known and a range comes with a score only."""
    try:
        metric_type = MetricType(metric_type)
    except ValueError as e:
        raise EngineError(f"unknown metric type {metric_type!r}") from e
    if metric_type is MetricType.SCORE and score_range is None:
        raise EngineError("a score metric needs its declared range")
    if metric_type is not MetricType.SCORE and score_range is not None:
        raise EngineError(f"a {metric_type.value} metric has no range")
    return metric_type
