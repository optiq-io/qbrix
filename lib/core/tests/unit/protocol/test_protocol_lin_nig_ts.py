"""Unit tests for LinNIGTSPolicy."""

import json

import numpy as np
import pytest

from qbrixcore.policy import POLICIES
from qbrixcore.policy.ts import LinNIGTSPolicy
from qbrixcore.policy.ts import LinNIGTSParamState
from qbrixcore.context import Context


def _ctx(vector) -> Context:
    return Context(id="ctx", vector=list(vector))


def _trained(num_arms: int, dim: int, samples: list[tuple[int, list, float]]):
    ps = LinNIGTSPolicy.build_state(num_arms=num_arms, dim=dim)
    for arm, x, y in samples:
        ps = LinNIGTSPolicy.train(ps, _ctx(x), arm, y)
    return ps


class TestLinNIGTSParamState:
    def test_defaults(self):
        ps = LinNIGTSParamState(num_arms=2, dim=3)

        assert ps.precision.shape == (2, 3, 3)
        assert np.array_equal(ps.precision[0], LinNIGTSPolicy.RIDGE * np.eye(3))
        assert ps.b.shape == (2, 3)
        assert np.array_equal(ps.y_sum, np.zeros(2))
        assert np.array_equal(ps.y_sq_sum, np.zeros(2))
        assert np.array_equal(ps.T, np.zeros(2))

    def test_dim_is_required(self):
        with pytest.raises(ValueError):
            LinNIGTSParamState(num_arms=2)

    def test_dim_positive(self):
        with pytest.raises(ValueError):
            LinNIGTSParamState(num_arms=2, dim=0)

    def test_json_round_trip(self):
        ps = _trained(2, 2, [(0, [1.0, 0.5], 42.0), (1, [1.0, -0.5], 7.5)])

        restored = LinNIGTSParamState.model_validate(
            json.loads(json.dumps(ps.model_dump()))
        )

        for field in ("precision", "b", "y_sum", "y_sq_sum", "T"):
            assert np.array_equal(getattr(restored, field), getattr(ps, field))


class TestLinNIGTSPolicy:
    def test_registered(self):
        assert LinNIGTSPolicy in POLICIES
        assert LinNIGTSPolicy.name == "LinNIGTSPolicy"

    def test_has_no_user_params(self):
        assert LinNIGTSPolicy.user_params() == []

    def test_train_accumulates_sufficient_statistics(self):
        ps = _trained(2, 2, [(0, [1.0, 2.0], 3.0), (0, [1.0, -1.0], 5.0)])

        expected = np.eye(2) + np.outer([1, 2], [1, 2]) + np.outer([1, -1], [1, -1])
        assert np.allclose(ps.precision[0], expected)
        assert np.allclose(ps.b[0], [8.0, 1.0])
        assert ps.y_sum[0] == 8.0
        assert ps.y_sq_sum[0] == 34.0
        assert list(ps.T) == [2, 0]
        assert np.array_equal(ps.precision[1], np.eye(2))

    def test_cold_arm_is_always_preferred(self):
        np.random.seed(0)
        ps = _trained(2, 1, [(0, [1.0], 100.0)] * 3 + [(1, [1.0], 1.0)])

        choices = {LinNIGTSPolicy.select(ps, _ctx([1.0])) for _ in range(200)}

        assert choices == {1}

    def test_ties_are_broken_at_random(self):
        np.random.seed(0)
        ps = LinNIGTSPolicy.build_state(num_arms=4, dim=2)

        choices = {LinNIGTSPolicy.select(ps, _ctx([1.0, 0.0])) for _ in range(200)}

        assert choices == {0, 1, 2, 3}

    def test_falls_back_to_pinv_mean_when_precision_is_singular(self):
        ps = LinNIGTSPolicy.build_state(
            num_arms=1,
            dim=2,
            precision=np.zeros((1, 2, 2)),
            b=np.array([[1.0, 2.0]]),
            T=np.array([5]),
        )

        theta = LinNIGTSPolicy._sample_theta(ps, 0)

        assert np.array_equal(theta, np.zeros(2))
