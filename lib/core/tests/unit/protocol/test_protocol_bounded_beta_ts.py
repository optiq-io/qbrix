"""Unit tests for BoundedBetaTSPolicy."""

import json

import numpy as np
import pytest

from qbrixcore.policy import POLICIES
from qbrixcore.policy.ts import BoundedBetaTSPolicy
from qbrixcore.policy.ts import BoundedBetaTSParamState
from qbrixcore.context import Context


@pytest.fixture
def ctx():
    return Context(id="ctx")


class TestBoundedBetaTSParamState:
    def test_defaults(self):
        ps = BoundedBetaTSParamState(num_arms=3)

        assert (ps.lo, ps.hi) == (0.0, 1.0)
        assert np.array_equal(ps.alpha, np.ones(3))
        assert np.array_equal(ps.beta, np.ones(3))
        assert np.array_equal(ps.T, np.zeros(3))

    def test_num_arms_positive(self):
        with pytest.raises(ValueError):
            BoundedBetaTSParamState(num_arms=0)

    @pytest.mark.parametrize("lo, hi", [(1.0, 1.0), (5.0, 1.0)])
    def test_empty_or_inverted_range_is_refused(self, lo, hi):
        with pytest.raises(ValueError, match="lo must be below hi"):
            BoundedBetaTSParamState(num_arms=2, lo=lo, hi=hi)

    def test_json_round_trip(self, ctx):
        ps = BoundedBetaTSPolicy.build_state(num_arms=2, lo=1.0, hi=5.0)
        for arm, y in [(0, 4.0), (1, 2.5), (0, 5.0)]:
            ps = BoundedBetaTSPolicy.train(ps, ctx, arm, y)

        restored = BoundedBetaTSParamState.model_validate(
            json.loads(json.dumps(ps.model_dump()))
        )

        assert (restored.lo, restored.hi) == (1.0, 5.0)
        assert np.array_equal(restored.alpha, ps.alpha)
        assert np.array_equal(restored.beta, ps.beta)
        assert np.array_equal(restored.T, ps.T)


class TestBoundedBetaTSPolicy:
    def test_registered(self):
        assert BoundedBetaTSPolicy in POLICIES
        assert BoundedBetaTSPolicy.name == "BoundedBetaTSPolicy"

    def test_has_no_user_params(self):
        assert BoundedBetaTSPolicy.user_params() == []

    def test_train_learns_from_the_whole_value(self, ctx):
        ps = BoundedBetaTSPolicy.build_state(num_arms=2)

        updated = BoundedBetaTSPolicy.train(ps, ctx, 0, 0.9)

        assert updated.alpha[0] == pytest.approx(1.9)
        assert updated.beta[0] == pytest.approx(1.1)
        assert updated.T[0] == 1

    def test_train_rescales_from_the_declared_range(self, ctx):
        ps = BoundedBetaTSPolicy.build_state(num_arms=2, lo=1.0, hi=5.0)

        updated = BoundedBetaTSPolicy.train(ps, ctx, 1, 4)

        assert updated.alpha[1] == pytest.approx(1.75)
        assert updated.beta[1] == pytest.approx(1.25)

    @pytest.mark.parametrize("reward, alpha, beta", [(-3.0, 1.0, 2.0), (9.0, 2.0, 1.0)])
    def test_out_of_range_value_is_clamped(self, ctx, reward, alpha, beta):
        ps = BoundedBetaTSPolicy.build_state(num_arms=1, lo=1.0, hi=5.0)

        updated = BoundedBetaTSPolicy.train(ps, ctx, 0, reward)

        assert updated.alpha[0] == alpha
        assert updated.beta[0] == beta
        assert updated.T[0] == 1

    def test_binary_rewards_match_beta_bernoulli(self, ctx):
        ps = BoundedBetaTSPolicy.build_state(num_arms=1)
        for y in [1, 0, 1, 1]:
            ps = BoundedBetaTSPolicy.train(ps, ctx, 0, y)

        assert ps.alpha[0] == 4.0
        assert ps.beta[0] == 2.0

    def test_train_leaves_other_arms_and_input_untouched(self, ctx):
        ps = BoundedBetaTSPolicy.build_state(num_arms=3)

        updated = BoundedBetaTSPolicy.train(ps, ctx, 1, 0.3)

        assert np.array_equal(ps.alpha, np.ones(3))
        assert np.array_equal(ps.beta, np.ones(3))
        assert list(updated.T) == [0, 1, 0]
        assert updated.alpha[0] == updated.alpha[2] == 1.0

    def test_ties_are_broken_at_random(self, ctx, monkeypatch):
        np.random.seed(0)
        ps = BoundedBetaTSPolicy.build_state(num_arms=4)
        monkeypatch.setattr(
            np.random, "beta", lambda a, b: np.full(len(a), 0.5, dtype=np.float64)
        )

        choices = {BoundedBetaTSPolicy.select(ps, ctx) for _ in range(200)}

        assert choices == {0, 1, 2, 3}

    def test_prefers_the_arm_with_higher_scores(self, ctx):
        np.random.seed(0)
        ps = BoundedBetaTSPolicy.build_state(num_arms=2)
        for _ in range(200):
            ps = BoundedBetaTSPolicy.train(ps, ctx, 0, 0.2)
            ps = BoundedBetaTSPolicy.train(ps, ctx, 1, 0.8)

        choices = [BoundedBetaTSPolicy.select(ps, ctx) for _ in range(100)]

        assert choices.count(1) > 95
