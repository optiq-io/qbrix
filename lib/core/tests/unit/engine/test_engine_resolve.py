"""Unit tests for resolving an engine and a metric type to a policy."""

import pytest

from qbrixcore.engine import Buridan
from qbrixcore.engine import EngineError
from qbrixcore.engine import Leibniz
from qbrixcore.engine import MetricType
from qbrixcore.engine import ScoreRange
from qbrixcore.engine import Spinoza
from qbrixcore.policy import POLICIES
from qbrixcore.policy.rand import RandomPolicy
from qbrixcore.policy.ts import BetaTSPolicy
from qbrixcore.policy.ts import BoundedBetaTSPolicy
from qbrixcore.policy.ts import BoundedLinNIGTSPolicy
from qbrixcore.policy.ts import GaussianNIGTSPolicy
from qbrixcore.policy.ts import LinNIGTSPolicy
from qbrixcore.policy.ts import LogisticTSPolicy

DIM = 4
RANGE = ScoreRange(1.0, 5.0)

PAIRS = [
    (
        Spinoza,
        MetricType.CONVERSION,
        BetaTSPolicy,
        {"alpha_prior": 1.0, "beta_prior": 1.0},
    ),
    (Spinoza, MetricType.COUNT, GaussianNIGTSPolicy, {}),
    (Spinoza, MetricType.VALUE, GaussianNIGTSPolicy, {}),
    (Spinoza, MetricType.SCORE, BoundedBetaTSPolicy, {"lo": 1.0, "hi": 5.0}),
    (
        Leibniz,
        MetricType.CONVERSION,
        LogisticTSPolicy,
        {"dim": DIM, "lambda_": 1.0, "lr": 0.1},
    ),
    (Leibniz, MetricType.COUNT, LinNIGTSPolicy, {"dim": DIM}),
    (Leibniz, MetricType.VALUE, LinNIGTSPolicy, {"dim": DIM}),
    (
        Leibniz,
        MetricType.SCORE,
        BoundedLinNIGTSPolicy,
        {"dim": DIM, "lo": 1.0, "hi": 5.0},
    ),
    (Buridan, MetricType.CONVERSION, RandomPolicy, {}),
    (Buridan, MetricType.COUNT, RandomPolicy, {}),
    (Buridan, MetricType.VALUE, RandomPolicy, {}),
    (Buridan, MetricType.SCORE, RandomPolicy, {}),
]


def _resolve(engine, metric_type):
    return engine.resolve(
        metric_type,
        score_range=RANGE if metric_type is MetricType.SCORE else None,
        context_dim=DIM,
    )


@pytest.mark.parametrize("engine, metric_type, policy_cls, fixed_params", PAIRS)
class TestEveryPair:
    def test_resolves_to_the_intended_policy(
        self, engine, metric_type, policy_cls, fixed_params
    ):
        resolved = _resolve(engine, metric_type)

        assert resolved.policy_cls is policy_cls
        assert dict(resolved.fixed_params) == fixed_params

    def test_fixed_params_build_a_state(
        self, engine, metric_type, policy_cls, fixed_params
    ):
        resolved = _resolve(engine, metric_type)

        ps = resolved.policy_cls.build_state(num_arms=3, **resolved.fixed_params)

        assert ps.num_arms == 3

    def test_every_user_param_is_pinned(
        self, engine, metric_type, policy_cls, fixed_params
    ):
        resolved = _resolve(engine, metric_type)

        user_params = {p.name for p in resolved.policy_cls.user_params()}

        assert user_params <= set(resolved.fixed_params)

    def test_resolved_policy_is_in_the_catalog(
        self, engine, metric_type, policy_cls, fixed_params
    ):
        assert _resolve(engine, metric_type).policy_cls in POLICIES


class TestRefusals:
    def test_leibniz_without_context_asks_for_a_schema(self):
        with pytest.raises(EngineError, match="declare a context schema"):
            Leibniz.resolve(MetricType.CONVERSION)

    @pytest.mark.parametrize("engine", [Spinoza, Buridan])
    def test_engines_without_context_need_none(self, engine):
        assert engine.resolve(MetricType.VALUE).policy_cls is not None

    @pytest.mark.parametrize("engine", [Spinoza, Leibniz, Buridan])
    def test_any_setting_is_refused(self, engine):
        with pytest.raises(EngineError, match="engines take no settings"):
            engine.resolve(
                MetricType.CONVERSION, context_dim=DIM, settings={"alpha_prior": 2.0}
            )

    def test_score_without_a_range_is_refused(self):
        with pytest.raises(EngineError, match="declared range"):
            Spinoza.resolve(MetricType.SCORE)

    def test_range_on_a_conversion_is_refused(self):
        with pytest.raises(EngineError, match="has no range"):
            Spinoza.resolve(MetricType.CONVERSION, score_range=RANGE)

    def test_unknown_metric_type_is_refused(self):
        with pytest.raises(EngineError, match="unknown metric type"):
            Spinoza.resolve("revenue")

    def test_metric_type_accepts_its_string_value(self):
        assert Spinoza.resolve("count").policy_cls is GaussianNIGTSPolicy

    @pytest.mark.parametrize("lo, hi", [(1.0, 1.0), (5.0, 1.0)])
    def test_empty_or_inverted_range_is_refused(self, lo, hi):
        with pytest.raises(EngineError, match="lo below hi"):
            ScoreRange(lo, hi)

    def test_fixed_params_cannot_be_changed(self):
        resolved = Spinoza.resolve(MetricType.CONVERSION)

        with pytest.raises(TypeError):
            resolved.fixed_params["alpha_prior"] = 5.0
