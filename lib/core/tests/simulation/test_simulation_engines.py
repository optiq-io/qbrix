"""Seeded share checks for every engine on every metric type."""

import random

import numpy as np
import pytest

from qbrixcore.context import Context
from qbrixcore.engine import Buridan
from qbrixcore.engine import Leibniz
from qbrixcore.engine import MetricType
from qbrixcore.engine import ScoreRange
from qbrixcore.engine import Spinoza

pytestmark = pytest.mark.slow

SEED = 2026
STEPS = 3000
WINDOW = 500
SCORE_RANGE = ScoreRange(1.0, 5.0)


def _lognormal(rng: np.random.Generator, mean: float) -> float:
    sigma = 0.8
    return float(rng.lognormal(np.log(mean) - sigma**2 / 2, sigma))


def _score(rng: np.random.Generator, mean: float) -> float:
    unit = (mean - SCORE_RANGE.lo) / (SCORE_RANGE.hi - SCORE_RANGE.lo)
    concentration = 4.0
    y = rng.beta(unit * concentration, (1 - unit) * concentration)
    return float(SCORE_RANGE.lo + (SCORE_RANGE.hi - SCORE_RANGE.lo) * y)


OUTCOMES = {
    MetricType.CONVERSION: ((0.05, 0.15), lambda rng, m: float(rng.random() < m)),
    MetricType.COUNT: ((3.0, 5.0), lambda rng, m: float(rng.poisson(m))),
    MetricType.VALUE: ((40.0, 60.0), _lognormal),
    MetricType.SCORE: ((3.0, 4.0), _score),
}


def _shares(engine, metric_type: MetricType, window: int = WINDOW) -> np.ndarray:
    """each option's share of the last window of decisions."""
    rng = np.random.default_rng(SEED)
    np.random.seed(SEED)
    random.seed(SEED)
    means, sample = OUTCOMES[metric_type]
    resolved = engine.resolve(
        metric_type,
        score_range=SCORE_RANGE if metric_type is MetricType.SCORE else None,
        context_dim=2,
    )
    policy = resolved.policy_cls
    ps = policy.build_state(num_arms=len(means), **resolved.fixed_params)

    picks = []
    for _ in range(STEPS):
        ctx = Context(id="ctx", vector=[1.0, float(rng.choice([0.0, 1.0]))])
        arm = policy.select(ps, ctx)
        ps = policy.train(ps, ctx, arm, sample(rng, means[arm]))
        picks.append(arm)
    return np.bincount(picks[-window:], minlength=len(means)) / window


@pytest.mark.parametrize("metric_type", list(MetricType))
@pytest.mark.parametrize("engine", [Spinoza, Leibniz])
def test_learning_engine_favours_the_better_option(engine, metric_type):
    shares = _shares(engine, metric_type)

    assert np.argmax(shares) == 1
    assert shares[1] > 0.7


@pytest.mark.parametrize("metric_type", list(MetricType))
def test_buridan_splits_evenly(metric_type):
    shares = _shares(Buridan, metric_type, window=STEPS)

    assert np.all(np.abs(shares - 0.5) < 0.05)
