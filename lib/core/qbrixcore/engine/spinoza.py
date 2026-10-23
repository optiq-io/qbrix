from __future__ import annotations

from qbrixcore.engine.base import BaseEngine
from qbrixcore.engine.base import Resolved
from qbrixcore.engine.metric import MetricType
from qbrixcore.engine.metric import ScoreRange
from qbrixcore.engine.spec import EngineVersion
from qbrixcore.policy.ts import BetaTSPolicy
from qbrixcore.policy.ts import BoundedBetaTSPolicy
from qbrixcore.policy.ts import GaussianNIGTSPolicy


class Spinoza(BaseEngine):
    """the default: finds what works for everyone and keeps a little doubt."""

    name = "spinoza"
    version = EngineVersion(1, 0)

    @classmethod
    def _resolve(
        cls,
        metric_type: MetricType,
        score_range: ScoreRange | None,
        context_dim: int | None,
    ) -> Resolved:
        if metric_type is MetricType.CONVERSION:
            return Resolved(BetaTSPolicy, {"alpha_prior": 1.0, "beta_prior": 1.0})
        if metric_type is MetricType.SCORE:
            return Resolved(
                BoundedBetaTSPolicy, {"lo": score_range.lo, "hi": score_range.hi}
            )
        return Resolved(GaussianNIGTSPolicy)
