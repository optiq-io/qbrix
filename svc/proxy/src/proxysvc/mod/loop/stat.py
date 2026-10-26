from __future__ import annotations

import math
from collections.abc import Sequence

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
DAY_MS = 24 * HOUR_MS

STEPS_MS = (
    MINUTE_MS,
    5 * MINUTE_MS,
    15 * MINUTE_MS,
    30 * MINUTE_MS,
    HOUR_MS,
    3 * HOUR_MS,
    6 * HOUR_MS,
    12 * HOUR_MS,
    DAY_MS,
)
MAX_COLUMNS = 48
Z_95 = 1.959963984540054


def step_for(span_ms: int) -> int:
    """the smallest step on the ladder that fits the span in MAX_COLUMNS."""
    for step in STEPS_MS:
        if span_ms <= step * MAX_COLUMNS:
            return step
    return STEPS_MS[-1]


def columns(since_ms: int, until_ms: int, step_ms: int) -> list[int]:
    """the step-aligned columns that cover [since, until), at most the last
    MAX_COLUMNS of them."""
    if until_ms <= since_ms:
        return []
    last = (until_ms - 1) // step_ms * step_ms
    first = max(since_ms // step_ms * step_ms, last - (MAX_COLUMNS - 1) * step_ms)
    return list(range(first, last + 1, step_ms))


def wilson(successes: float, n: int) -> tuple[float, float]:
    p = successes / n
    z2 = Z_95 * Z_95
    denominator = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denominator
    half = Z_95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def normal(n: int, total: float, total_sq: float) -> tuple[float, float] | None:
    """mean ± z·s/√n with the sample's own spread; none below two values."""
    if n < 2:
        return None
    mean = total / n
    variance = max(0.0, (total_sq - n * mean * mean) / (n - 1))
    half = Z_95 * math.sqrt(variance / n)
    return mean - half, mean + half


def option_range(
    metric_type: str, n: int, total: float, total_sq: float
) -> tuple[float, float] | None:
    """the 95% range of an option's mean value per sealed decision."""
    if n == 0:
        return None
    if metric_type == "conversion":
        return wilson(total, n)
    return normal(n, total, total_sq)


def lift(options: Sequence[tuple[int, float]]) -> float | None:
    """the mean value per sealed decision over the unweighted average of each
    option's mean, minus one: how much better the loop did than an even split
    of the same options. none while any option has no sealed decision."""
    if not options or any(n == 0 for n, _ in options):
        return None
    baseline = sum(total / n for n, total in options) / len(options)
    if baseline == 0:
        return None
    mean = sum(total for _, total in options) / sum(n for n, _ in options)
    return mean / baseline - 1
