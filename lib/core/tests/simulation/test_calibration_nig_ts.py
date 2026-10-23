"""Seeded calibration and regret checks for the policies that learn the spread."""

import numpy as np
import pytest

from qbrixcore.policy.ts import GaussianNIGTSPolicy
from qbrixcore.policy.ts import GaussianTSPolicy
from qbrixcore.policy.ts import LinNIGTSPolicy
from qbrixcore.context import Context

pytestmark = pytest.mark.slow

SEED = 2026
RUNS = 600
OUTCOMES_PER_RUN = 200
DRAWS = 2000

REVENUE_MEAN = 40.0
REVENUE_SIGMA = 0.8


def _revenue(rng: np.random.Generator, mean: float, size) -> np.ndarray:
    mu = np.log(mean) - REVENUE_SIGMA**2 / 2
    return rng.lognormal(mu, REVENUE_SIGMA, size)


def _nig_interval(rewards: np.ndarray) -> tuple[float, float]:
    ctx = Context(id="ctx")
    ps = GaussianNIGTSPolicy.build_state(num_arms=1)
    for y in rewards:
        ps = GaussianNIGTSPolicy.train(ps, ctx, 0, y)

    replicated = GaussianNIGTSPolicy.build_state(
        num_arms=DRAWS,
        T=np.repeat(ps.T, DRAWS),
        mean=np.repeat(ps.mean, DRAWS),
        m2=np.repeat(ps.m2, DRAWS),
    )
    lo, hi = np.percentile(GaussianNIGTSPolicy._sample_means(replicated), [5, 95])
    return lo, hi


def _fixed_precision_interval(rewards: np.ndarray) -> tuple[float, float]:
    ctx = Context(id="ctx")
    ps = GaussianTSPolicy.build_state(num_arms=1)
    for y in rewards:
        ps = GaussianTSPolicy.train(ps, ctx, 0, y)

    draws = np.random.normal(
        ps.posterior_mean[0], 1.0 / np.sqrt(ps.posterior_precision[0]), DRAWS
    )
    lo, hi = np.percentile(draws, [5, 95])
    return lo, hi


def _coverage(interval, sample, true_mean: float) -> float:
    rng = np.random.default_rng(SEED)
    np.random.seed(SEED)
    hits = 0
    for _ in range(RUNS):
        lo, hi = interval(sample(rng))
        hits += lo <= true_mean <= hi
    return hits / RUNS


class TestGaussianNIGCalibration:
    def test_interval_covers_revenue_scale_mean_at_nominal_rate(self):
        coverage = _coverage(
            _nig_interval,
            lambda rng: _revenue(rng, REVENUE_MEAN, OUTCOMES_PER_RUN),
            REVENUE_MEAN,
        )

        assert 0.85 <= coverage <= 0.95

    def test_interval_covers_unit_scale_mean_at_nominal_rate(self):
        coverage = _coverage(
            _nig_interval,
            lambda rng: rng.normal(0.3, 0.1, OUTCOMES_PER_RUN),
            0.3,
        )

        assert 0.85 <= coverage <= 0.95

    def test_fixed_precision_policy_is_overconfident_on_revenue_scale(self):
        coverage = _coverage(
            _fixed_precision_interval,
            lambda rng: _revenue(rng, REVENUE_MEAN, OUTCOMES_PER_RUN),
            REVENUE_MEAN,
        )

        assert coverage < 0.2

    def test_better_revenue_arm_wins_share(self):
        rng = np.random.default_rng(SEED)
        np.random.seed(SEED)
        ctx = Context(id="ctx")
        means = [REVENUE_MEAN, REVENUE_MEAN * 1.2]
        ps = GaussianNIGTSPolicy.build_state(num_arms=2)

        choices = []
        for _ in range(3000):
            arm = GaussianNIGTSPolicy.select(ps, ctx)
            ps = GaussianNIGTSPolicy.train(
                ps, ctx, arm, float(_revenue(rng, means[arm], None))
            )
            choices.append(arm)

        assert np.mean(np.array(choices[-1000:]) == 1) > 0.8


class TestLinNIGCalibration:
    def test_learns_noise_variance(self):
        rng = np.random.default_rng(SEED)
        theta = np.array([1.0, 2.0, -1.0])
        sigma = 2.0
        ps = LinNIGTSPolicy.build_state(num_arms=1, dim=3)

        for _ in range(2000):
            x = rng.normal(size=3)
            y = float(theta @ x + rng.normal(0.0, sigma))
            ps = LinNIGTSPolicy.train(ps, Context(id="ctx", vector=x.tolist()), 0, y)

        mu = np.linalg.solve(ps.precision[0], ps.b[0])
        shape, scale = LinNIGTSPolicy._noise_posterior(ps, 0, mu)

        assert scale / (shape - 1.0) == pytest.approx(sigma**2, rel=0.2)

    def test_better_arm_per_context_wins_share(self):
        rng = np.random.default_rng(SEED)
        np.random.seed(SEED)
        thetas = np.array([[40.0, 8.0], [40.0, -8.0]])
        ps = LinNIGTSPolicy.build_state(num_arms=2, dim=2)

        best_picked = {1.0: [], -1.0: []}
        for _ in range(3000):
            segment = float(rng.choice([1.0, -1.0]))
            x = np.array([1.0, segment])
            ctx = Context(id="ctx", vector=x.tolist())
            arm = LinNIGTSPolicy.select(ps, ctx)
            y = float(thetas[arm] @ x + rng.normal(0.0, 15.0))
            ps = LinNIGTSPolicy.train(ps, ctx, arm, y)
            best_picked[segment].append(arm == (0 if segment > 0 else 1))

        for picks in best_picked.values():
            assert np.mean(picks[-500:]) > 0.8
