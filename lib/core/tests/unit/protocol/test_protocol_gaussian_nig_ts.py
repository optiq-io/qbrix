"""Unit tests for GaussianNIGTSPolicy."""

import json

import numpy as np
import pytest

from qbrixcore.policy import POLICIES
from qbrixcore.policy.ts import GaussianNIGTSPolicy
from qbrixcore.policy.ts import GaussianNIGTSParamState
from qbrixcore.context import Context


@pytest.fixture
def ctx():
    return Context(id="ctx")


def _trained(rewards_per_arm: list[list[float]], ctx: Context):
    ps = GaussianNIGTSPolicy.build_state(num_arms=len(rewards_per_arm))
    for arm, rewards in enumerate(rewards_per_arm):
        for y in rewards:
            ps = GaussianNIGTSPolicy.train(ps, ctx, arm, y)
    return ps


class TestGaussianNIGTSParamState:
    def test_defaults(self):
        ps = GaussianNIGTSParamState(num_arms=3)

        assert np.array_equal(ps.T, np.zeros(3))
        assert np.array_equal(ps.mean, np.zeros(3))
        assert np.array_equal(ps.m2, np.zeros(3))

    def test_num_arms_positive(self):
        with pytest.raises(ValueError):
            GaussianNIGTSParamState(num_arms=0)

    def test_json_round_trip(self, ctx):
        ps = _trained([[12.5, 40.0, 3.25], [0.0, 99.9]], ctx)

        restored = GaussianNIGTSParamState.model_validate(
            json.loads(json.dumps(ps.model_dump()))
        )

        assert np.array_equal(restored.T, ps.T)
        assert np.array_equal(restored.mean, ps.mean)
        assert np.array_equal(restored.m2, ps.m2)


class TestGaussianNIGTSPolicy:
    def test_registered(self):
        assert GaussianNIGTSPolicy in POLICIES
        assert GaussianNIGTSPolicy.name == "GaussianNIGTSPolicy"

    def test_has_no_user_params(self):
        assert GaussianNIGTSPolicy.user_params() == []

    def test_train_matches_sample_mean_and_variance(self, ctx):
        rng = np.random.default_rng(0)
        rewards = rng.lognormal(3.5, 0.8, 500)

        ps = _trained([rewards.tolist()], ctx)

        assert ps.T[0] == 500
        assert ps.mean[0] == pytest.approx(np.mean(rewards))
        assert ps.m2[0] / (ps.T[0] - 1) == pytest.approx(np.var(rewards, ddof=1))

    def test_train_leaves_other_arms_untouched(self, ctx):
        ps = _trained([[1.0, 2.0], [], [5.0]], ctx)

        assert list(ps.T) == [2, 0, 1]
        assert ps.mean[1] == 0.0
        assert ps.m2[1] == 0.0

    def test_cold_arm_is_always_preferred(self, ctx):
        np.random.seed(0)
        ps = _trained([[100.0, 110.0, 90.0], [1.0]], ctx)

        choices = {GaussianNIGTSPolicy.select(ps, ctx) for _ in range(200)}

        assert choices == {1}

    def test_ties_are_broken_at_random(self, ctx):
        np.random.seed(0)
        ps = GaussianNIGTSPolicy.build_state(num_arms=4)

        choices = {GaussianNIGTSPolicy.select(ps, ctx) for _ in range(200)}

        assert choices == {0, 1, 2, 3}

    def test_identical_outcomes_on_every_arm_tie_at_random(self, ctx):
        np.random.seed(0)
        ps = _trained([[0.0] * 5, [0.0] * 5, [0.0] * 5], ctx)

        choices = {GaussianNIGTSPolicy.select(ps, ctx) for _ in range(200)}

        assert choices == {0, 1, 2}

    def test_constant_arm_keeps_uncertainty_from_pooled_spread(self, ctx):
        np.random.seed(0)
        rng = np.random.default_rng(0)
        ps = _trained([[0.0] * 30, rng.normal(40.0, 20.0, 30).tolist()], ctx)

        draws = np.array([GaussianNIGTSPolicy._sample_means(ps)[0] for _ in range(500)])

        assert np.std(draws) > 0.0
        assert abs(np.mean(draws)) < 5.0

    def test_scale_invariant(self, ctx):
        rng = np.random.default_rng(1)
        rewards = [
            rng.normal(0.3, 0.1, 50).tolist(),
            rng.normal(0.35, 0.1, 50).tolist(),
        ]
        small = _trained(rewards, ctx)
        large = _trained([[y * 1000.0 for y in r] for r in rewards], ctx)

        np.random.seed(7)
        small_choices = [GaussianNIGTSPolicy.select(small, ctx) for _ in range(100)]
        np.random.seed(7)
        large_choices = [GaussianNIGTSPolicy.select(large, ctx) for _ in range(100)]

        assert small_choices == large_choices
