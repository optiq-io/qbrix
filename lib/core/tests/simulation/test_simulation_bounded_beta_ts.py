"""Seeded share checks for BoundedBetaTSPolicy against BetaTSPolicy's 0.5 cut."""

import numpy as np
import pytest

from qbrixcore.policy.ts import BetaTSPolicy
from qbrixcore.policy.ts import BoundedBetaTSPolicy
from qbrixcore.context import Context

pytestmark = pytest.mark.slow

SEED = 2026
RUNS = 100
STEPS = 1000
WINDOW = 200

WORSE_MEAN = 0.58
BETTER_MEAN = 0.62


def _beta_scores(concentration: float):
    def sample(rng: np.random.Generator, arm: int) -> float:
        mean = BETTER_MEAN if arm == 1 else WORSE_MEAN
        return float(rng.beta(mean * concentration, (1 - mean) * concentration))

    return sample


def _cut_disagrees_with_mean(rng: np.random.Generator, arm: int) -> float:
    if arm == 1:
        return 0.49 if rng.random() < 0.7 else 0.92
    return float(np.clip(rng.normal(WORSE_MEAN, 0.02), 0.0, 1.0))


def _better_share(policy, sample, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    """share of the better arm per step, averaged over seeded runs."""
    rng = np.random.default_rng(SEED)
    np.random.seed(SEED)
    ctx = Context(id="ctx")
    state_params = {"lo": lo, "hi": hi} if policy is BoundedBetaTSPolicy else {}

    picks = np.zeros((RUNS, STEPS))
    for run in range(RUNS):
        ps = policy.build_state(num_arms=2, **state_params)
        for step in range(STEPS):
            arm = policy.select(ps, ctx)
            y = lo + (hi - lo) * sample(rng, arm)
            ps = policy.train(ps, ctx, arm, y)
            picks[run, step] = arm
    return picks.mean(axis=0)


def _first(share: np.ndarray) -> float:
    return float(share[:WINDOW].mean())


def _last(share: np.ndarray) -> float:
    return float(share[-WINDOW:].mean())


class TestBoundedBetaTSShare:
    def test_better_scoring_arm_wins_share(self):
        share = _better_share(BoundedBetaTSPolicy, _beta_scores(2.0))

        assert _last(share) > _first(share)
        assert _last(share) > 0.75

    def test_declared_range_learns_like_unit_range(self):
        unit = _better_share(BoundedBetaTSPolicy, _beta_scores(2.0))
        five_point = _better_share(BoundedBetaTSPolicy, _beta_scores(2.0), 1.0, 5.0)

        np.testing.assert_allclose(five_point, unit)


class TestAgainstHalfCut:
    def test_cut_converges_on_the_worse_arm_when_it_disagrees_with_the_mean(self):
        bounded = _better_share(BoundedBetaTSPolicy, _cut_disagrees_with_mean)
        cut = _better_share(BetaTSPolicy, _cut_disagrees_with_mean)

        assert _last(bounded) > 0.75
        assert _last(cut) < 0.05

    def test_wide_scores_learn_at_least_as_fast_as_the_cut(self):
        bounded = _better_share(BoundedBetaTSPolicy, _beta_scores(2.0))
        cut = _better_share(BetaTSPolicy, _beta_scores(2.0))

        assert _last(bounded) >= _last(cut) - 0.03

    def test_tight_scores_learn_slower_than_the_cut(self):
        bounded = _better_share(BoundedBetaTSPolicy, _beta_scores(30.0))
        cut = _better_share(BetaTSPolicy, _beta_scores(30.0))

        assert _last(cut) > _last(bounded) + 0.05
