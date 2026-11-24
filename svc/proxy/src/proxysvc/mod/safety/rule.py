from __future__ import annotations

from datetime import datetime
from datetime import timezone

from qbrixstore.redis.health import CALLS_STOPPED_MIN_CALLS
from qbrixstore.redis.health import DECISION_ERROR_MIN_CALLS
from qbrixstore.redis.health import DECISION_ERROR_RATE
from qbrixstore.redis.health import Intake
from qbrixstore.redis.health import NOT_LEARNED_MIN_OUTCOMES
from qbrixstore.redis.health import NOT_LEARNED_RATE
from qbrixstore.redis.health import NOT_LEARNED_WINDOW_MINUTES
from qbrixstore.redis.health import OUTCOMES_STOPPED_GAP_FACTOR
from qbrixstore.redis.health import OUTCOMES_STOPPED_MIN_DECISIONS
from qbrixstore.redis.health import OUTCOMES_STOPPED_MIN_MINUTES
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.health import OutcomeHealth
from qbrixstore.redis.health import SelectHealth

DECISION_ERRORS = "decision_errors"
OUTCOMES_STOPPED = "outcomes_stopped"
OUTCOMES_NOT_LEARNED = "outcomes_not_learned"
CALLS_STOPPED = "calls_stopped"
WARNINGS = (OUTCOMES_STOPPED, OUTCOMES_NOT_LEARNED, CALLS_STOPPED)

HOUR_MS = 60 * 60 * 1000
DAY_HOURS = 24

# train_error may still learn, earlier_cycle says nothing of this cycle's
# wiring, and an unattributed event belongs to no cycle
NOT_LEARNED = (
    OutcomeDisposition.LATE,
    OutcomeDisposition.DUPLICATE,
    OutcomeDisposition.INVALID,
)


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


def outcomes_stopped(
    intake: Intake,
    *,
    window_ms: int,
    silent_since_ms: int,
    now_ms: int,
    deciding: bool,
) -> bool:
    """decisions keep being made and outcomes stopped arriving: a whole
    window passed with none, or half an hour did and the decisions since the
    last one are more than ten times the cycle's usual decisions per outcome.

    ``silent_since_ms`` is the latest of the last outcome, when the loop last
    started serving and when its cycle started, so a resume restarts the
    clock. a cycle with no outcome yet has only the whole-window test.
    """
    if not deciding or intake.since_outcome < OUTCOMES_STOPPED_MIN_DECISIONS:
        return False
    silent_ms = now_ms - silent_since_ms
    if silent_ms >= window_ms:
        return True
    if silent_ms < OUTCOMES_STOPPED_MIN_MINUTES * 60_000 or not intake.outcomes:
        return False
    return intake.since_outcome > OUTCOMES_STOPPED_GAP_FACTOR * _usual(intake)


def _usual(intake: Intake) -> float:
    """decisions per outcome up to the last outcome."""
    return (intake.decisions - intake.since_outcome) / intake.outcomes


def stopped_evidence(
    intake: Intake, *, window_ms: int, silent_since_ms: int, now_ms: int
) -> dict:
    return {
        "signal": OUTCOMES_STOPPED,
        "decisions_since_outcome": intake.since_outcome,
        "usual_decisions_per_outcome": (
            round(_usual(intake), 1) if intake.outcomes else None
        ),
        "last_outcome_at": (
            _iso(intake.last_outcome_ms / 1000)
            if intake.last_outcome_ms is not None
            else None
        ),
        "silent_since": _iso(silent_since_ms / 1000),
        "window_sec": window_ms // 1000,
        "checked_at": _iso(now_ms / 1000),
    }


def _not_learned_counts(health: OutcomeHealth) -> tuple[int, int]:
    missed = sum(health.by_reason.get(d.value, 0) for d in NOT_LEARNED)
    return missed, missed + health.learned


def outcomes_not_learned(health: OutcomeHealth) -> bool:
    """more than a tenth of the hour's outcomes couldn't be learned from,
    over enough outcomes to say so."""
    missed, outcomes = _not_learned_counts(health)
    return outcomes >= NOT_LEARNED_MIN_OUTCOMES and missed / outcomes > NOT_LEARNED_RATE


def not_learned_evidence(health: OutcomeHealth, now_ms: int) -> dict:
    missed, outcomes = _not_learned_counts(health)
    return {
        "signal": OUTCOMES_NOT_LEARNED,
        "rate": round(missed / outcomes, 4) if outcomes else 0.0,
        "not_learned": missed,
        "outcomes": outcomes,
        "reasons": {
            d.value: health.by_reason[d.value]
            for d in NOT_LEARNED
            if health.by_reason.get(d.value)
        },
        "window_minutes": NOT_LEARNED_WINDOW_MINUTES,
        "checked_at": _iso(now_ms / 1000),
    }


def calls_silent(*, last_hour: int, this_hour: int) -> bool:
    """no call since the last full hour began."""
    return last_hour == 0 and this_hour == 0


def calls_stopped(
    *,
    last_hour: int,
    this_hour: int,
    yesterday: int,
    hour: int,
    serving_since_ms: int,
) -> bool:
    """a loop deciding through the last full hour and the same hour
    yesterday had no call since the last full hour began, and at least 60
    in the same hour yesterday. ``hour`` is the current one, in whole hours
    since the epoch, so a quiet night compares with the night before."""
    yesterday_start_ms = (hour - 1 - DAY_HOURS) * HOUR_MS
    return (
        calls_silent(last_hour=last_hour, this_hour=this_hour)
        and yesterday >= CALLS_STOPPED_MIN_CALLS
        and serving_since_ms <= yesterday_start_ms
    )


def calls_evidence(*, yesterday: int, hour: int, now_ms: int) -> dict:
    return {
        "signal": CALLS_STOPPED,
        "calls_same_hour_yesterday": yesterday,
        "silent_since": _iso((hour - 1) * HOUR_MS / 1000),
        "yesterday_hour_start": _iso((hour - 1 - DAY_HOURS) * HOUR_MS / 1000),
        "checked_at": _iso(now_ms / 1000),
    }


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
