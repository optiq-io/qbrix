from __future__ import annotations

from datetime import datetime
from datetime import timezone

from qbrixstore.redis.health import DECISION_ERROR_MIN_CALLS
from qbrixstore.redis.health import DECISION_ERROR_RATE
from qbrixstore.redis.health import SelectHealth

DECISION_ERRORS = "decision_errors"


def unhealthy(health: SelectHealth) -> bool:
    """qbrix failed more than its share of a loop's calls, over enough calls
    to say so."""
    return (
        health.calls >= DECISION_ERROR_MIN_CALLS
        and health.error_rate > DECISION_ERROR_RATE
    )


def evidence(health: SelectHealth, first_minute: int, now_sec: float) -> dict:
    return {
        "signal": DECISION_ERRORS,
        "rate": round(health.error_rate, 4),
        "errors": health.error,
        "calls": health.calls,
        "window_start": _iso(first_minute * 60),
        "window_end": _iso(now_sec),
        "reasons": dict(health.by_reason),
    }


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
