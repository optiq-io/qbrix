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
