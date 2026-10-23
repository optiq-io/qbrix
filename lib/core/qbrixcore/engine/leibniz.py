from __future__ import annotations

from qbrixcore.engine.base import BaseEngine
from qbrixcore.engine.base import Resolved
from qbrixcore.engine.metric import MetricType
from qbrixcore.engine.metric import ScoreRange
from qbrixcore.engine.spec import EngineVersion
from qbrixcore.policy.ts import BoundedLinNIGTSPolicy
from qbrixcore.policy.ts import LinNIGTSPolicy
from qbrixcore.policy.ts import LogisticTSPolicy


class Leibniz(BaseEngine):
    """personalization: different options for different requests, by context."""

    name = "leibniz"
    version = EngineVersion(1, 0)
    needs_context = True

    @classmethod
    def _resolve(
        cls,
        metric_type: MetricType,
        score_range: ScoreRange | None,
        context_dim: int | None,
    ) -> Resolved:
        if metric_type is MetricType.CONVERSION:
            return Resolved(
                LogisticTSPolicy, {"dim": context_dim, "lambda_": 1.0, "lr": 0.1}
            )
        if metric_type is MetricType.SCORE:
            return Resolved(
                BoundedLinNIGTSPolicy,
                {"dim": context_dim, "lo": score_range.lo, "hi": score_range.hi},
            )
        return Resolved(LinNIGTSPolicy, {"dim": context_dim})
