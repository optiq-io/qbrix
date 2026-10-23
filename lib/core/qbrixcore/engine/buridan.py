from __future__ import annotations

from qbrixcore.engine.base import BaseEngine
from qbrixcore.engine.base import Resolved
from qbrixcore.engine.metric import MetricType
from qbrixcore.engine.metric import ScoreRange
from qbrixcore.engine.spec import EngineVersion
from qbrixcore.policy.rand import RandomPolicy


class Buridan(BaseEngine):
    """an even split that never prefers an option."""

    name = "buridan"
    version = EngineVersion(1, 0)

    @classmethod
    def _resolve(
        cls,
        metric_type: MetricType,
        score_range: ScoreRange | None,
        context_dim: int | None,
    ) -> Resolved:
        return Resolved(RandomPolicy)
