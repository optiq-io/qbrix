from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from importlib.metadata import version

from qbrixstore.redis.health import LedgerProgress

LEARNING_BEHIND_MS = 2 * 60 * 1000

VERSION = version("proxysvc")


@dataclass(frozen=True)
class Services:
    storage: bool
    deciding: bool
    learning: bool


@dataclass(frozen=True)
class Learning:
    """how far learning trails the ledger; behind when cortex hasn't checked
    recently enough to have left its progress, or trails past the limit."""

    lag_ms: int | None
    checked_at: str | None
    behind: bool


@dataclass(frozen=True)
class WorkspaceStatus:
    version: str
    services: Services
    learning: Learning


def learning(progress: LedgerProgress | None) -> Learning:
    if progress is None:
        return Learning(lag_ms=None, checked_at=None, behind=True)
    checked = datetime.fromtimestamp(progress.checked_ms / 1000, tz=timezone.utc)
    return Learning(
        lag_ms=progress.lag_ms,
        checked_at=checked.isoformat(),
        behind=progress.lag_ms > LEARNING_BEHIND_MS,
    )


def workspace_status(
    services: Services, progress: LedgerProgress | None
) -> WorkspaceStatus:
    return WorkspaceStatus(
        version=VERSION, services=services, learning=learning(progress)
    )
