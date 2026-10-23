import numpy as np


def sigmoid(z: np.ndarray) -> np.ndarray:
    """numerically stable sigmoid."""
    return np.where(
        z >= 0,
        1.0 / (1.0 + np.exp(-z)),
        np.exp(z) / (1.0 + np.exp(z)),
    )


def argmax_random_tiebreak(values) -> int:
    """argmax with random tie-breaking.

    np.argmax always returns the first index on ties, which causes arm-0
    bias in concurrent selection (motorsvc reads stale cached params where
    all arms are equal). this picks uniformly among tied maxima instead.
    """
    a = np.asarray(values, dtype=np.float64)
    max_val = np.max(a)
    candidates = np.flatnonzero(a == max_val)
    return int(np.random.choice(candidates))


def unit_interval(value: float, lo: float, hi: float) -> float:
    """rescale value from [lo, hi] onto [0, 1], clamping anything outside."""
    return float(np.clip((float(value) - lo) / (hi - lo), 0.0, 1.0))
