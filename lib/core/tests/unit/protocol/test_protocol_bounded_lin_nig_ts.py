"""Unit tests for BoundedLinNIGTSPolicy."""

import json

import numpy as np
import pytest

from qbrixcore.policy import POLICIES
from qbrixcore.policy.ts import BoundedLinNIGTSPolicy
from qbrixcore.policy.ts import BoundedLinNIGTSParamState
from qbrixcore.policy.ts import LinNIGTSPolicy
from qbrixcore.context import Context


def _ctx(x):
    return Context(id="ctx", vector=list(x))


class TestBoundedLinNIGTSParamState:
    def test_defaults(self):
        ps = BoundedLinNIGTSParamState(num_arms=2, dim=3)

        assert (ps.lo, ps.hi) == (0.0, 1.0)
        assert ps.precision.shape == (2, 3, 3)

    @pytest.mark.parametrize("lo, hi", [(2.0, 2.0), (5.0, 1.0)])
    def test_empty_or_inverted_range_is_refused(self, lo, hi):
        with pytest.raises(ValueError, match="lo must be below hi"):
            BoundedLinNIGTSParamState(num_arms=2, dim=3, lo=lo, hi=hi)

    def test_json_round_trip(self):
        ps = BoundedLinNIGTSPolicy.build_state(num_arms=2, dim=2, lo=1.0, hi=5.0)
        ps = BoundedLinNIGTSPolicy.train(ps, _ctx([1.0, 0.5]), 1, 4.0)

        restored = BoundedLinNIGTSParamState.model_validate(
            json.loads(json.dumps(ps.model_dump()))
        )

        assert (restored.lo, restored.hi) == (1.0, 5.0)
        assert np.array_equal(restored.b, ps.b)
        assert np.array_equal(restored.precision, ps.precision)


class TestBoundedLinNIGTSPolicy:
    def test_registered_without_user_params(self):
        assert BoundedLinNIGTSPolicy in POLICIES
        assert BoundedLinNIGTSPolicy.user_params() == []

    def test_learns_the_rescaled_value(self):
        ps = BoundedLinNIGTSPolicy.build_state(num_arms=1, dim=2, lo=1.0, hi=5.0)

        ps = BoundedLinNIGTSPolicy.train(ps, _ctx([1.0, 2.0]), 0, 4.0)

        assert ps.y_sum[0] == pytest.approx(0.75)
        assert np.allclose(ps.b[0], [0.75, 1.5])

    @pytest.mark.parametrize("reward, y", [(-3.0, 0.0), (9.0, 1.0)])
    def test_out_of_range_value_is_clamped(self, reward, y):
        ps = BoundedLinNIGTSPolicy.build_state(num_arms=1, dim=1, lo=1.0, hi=5.0)

        ps = BoundedLinNIGTSPolicy.train(ps, _ctx([1.0]), 0, reward)

        assert ps.y_sum[0] == y
        assert ps.T[0] == 1

    def test_matches_lin_nig_on_unit_range_data(self):
        rng = np.random.default_rng(0)
        bounded = BoundedLinNIGTSPolicy.build_state(num_arms=2, dim=2)
        plain = LinNIGTSPolicy.build_state(num_arms=2, dim=2)
        for _ in range(50):
            ctx = _ctx([1.0, float(rng.random())])
            arm = int(rng.integers(2))
            y = float(rng.random())
            bounded = BoundedLinNIGTSPolicy.train(bounded, ctx, arm, y)
            plain = LinNIGTSPolicy.train(plain, ctx, arm, y)

        assert np.allclose(bounded.b, plain.b)
        assert np.allclose(bounded.y_sq_sum, plain.y_sq_sum)

        np.random.seed(3)
        bounded_choice = BoundedLinNIGTSPolicy.select(bounded, _ctx([1.0, 0.5]))
        np.random.seed(3)
        plain_choice = LinNIGTSPolicy.select(plain, _ctx([1.0, 0.5]))
        assert bounded_choice == plain_choice
