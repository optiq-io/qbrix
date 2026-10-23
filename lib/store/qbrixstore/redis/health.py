from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum

SELECT_HEALTH_TTL_SEC = 2 * 60 * 60


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


@dataclass(frozen=True)
class SelectHealth:
    """how an experiment's select calls ended over a window of minutes."""

    ok: int = 0
    client: int = 0
    error: int = 0
    not_found: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
