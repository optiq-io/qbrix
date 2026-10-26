from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum

SELECT_HEALTH_TTL_SEC = 2 * 60 * 60
OUTCOME_HEALTH_TTL_SEC = 26 * 60 * 60
LEDGER_PROGRESS_TTL_SEC = 5 * 60


class SelectOutcome(str, Enum):
    OK = "ok"
    CLIENT = "client"
    ERROR = "error"
    NOT_FOUND = "not_found"


class SelectErrorReason(str, Enum):
    STORE = "store"
    GATE = "gate"
    MOTOR_UNAVAILABLE = "motor_unavailable"
    MOTOR_TIMEOUT = "motor_timeout"
    MOTOR_INTERNAL = "motor_internal"
    CONFIG = "config"
    INTERNAL = "internal"


class LoopSelectReason(str, Enum):
    """why a loop's select answered as it did."""

    LIVE = "live"
    DRAFT = "draft"
    PAUSED = "paused"


@dataclass(frozen=True)
class SelectHealth:
    """how an experiment's select calls ended over a window of minutes."""

    ok: int = 0
    client: int = 0
    error: int = 0
    not_found: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)


class OutcomeDisposition(str, Enum):
    LEARNED = "learned"
    UNKNOWN_EXPERIMENT = "unknown_experiment"
    PAUSED = "paused"
    UNKNOWN_POLICY = "unknown_policy"
    TRAIN_ERROR = "train_error"
    REJECTED_TOKEN_EXPIRED = "rejected_token_expired"
    INVALID = "invalid"
    LATE = "late"
    DUPLICATE = "duplicate"
    EARLIER_CYCLE = "earlier_cycle"


@dataclass(frozen=True)
class LedgerProgress:
    """the ledger time before which every decision and outcome is written,
    and how far that trails the moment it was checked."""

    complete_up_to_ms: int
    lag_ms: int
    checked_ms: int


@dataclass(frozen=True)
class OutcomeHealth:
    """how an experiment's outcomes ended over a window of minutes, and when
    the last one arrived.

    ``train_error`` is counted on an outcome's first failed attempt, so an
    outcome that later trains appears under it and under ``learned``.
    """

    learned: int = 0
    not_learned: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    last_arrival_ms: int | None = None
