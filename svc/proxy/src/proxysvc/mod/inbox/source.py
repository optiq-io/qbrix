from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Literal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.service import workspace_rows
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.summary.entry import ALERT_KINDS
from proxysvc.mod.summary.entry import SAFETY_PAUSE
from proxysvc.mod.summary.entry import is_safety_pause
from proxysvc.mod.summary.entry import opened

Section = Literal["waiting", "notified", "alerts", "suggestions"]

ASKED_WITHIN = timedelta(days=30)
NOTIFIED_WITHIN = timedelta(days=7)
NOTIFIED_MAX = 100


@dataclass(frozen=True, slots=True)
class Reader:
    """whose inbox is read, and whether their role makes changes."""

    tenant_id: str
    user_id: str
    can_change: bool


class Source(Protocol):
    """one kind of inbox item. needs_change keeps it from a reader whose role
    makes no changes, such as a viewer."""

    section: Section
    needs_change: bool

    async def items(
        self, session: AsyncSession, reader: Reader, now: datetime
    ) -> list[dict]: ...


def _item(kind: str, at: datetime, **parts: dict | None) -> dict:
    return {
        "kind": kind,
        "at": at.isoformat(),
        "change": None,
        "asked": None,
        "loop": None,
        "alert": None,
        **parts,
    }


class WaitingSource:
    """changes the reader's connections asked for, each with how often its
    connection asked for that kind lately and was approved, for raising its
    level."""

    section: Section = "waiting"
    needs_change = True

    async def items(
        self, session: AsyncSession, reader: Reader, now: datetime
    ) -> list[dict]:
        repo = ChangeRepository(session, reader.tenant_id)
        changes = await repo.waiting_for(reader.user_id)
        if not changes:
            return []
        rows = await workspace_rows(
            session, reader.tenant_id, [[change] for change in changes]
        )
        since = now - ASKED_WITHIN
        asked = await repo.asked_by(
            reader.user_id, {change.connection_id for change in changes}, since
        )
        undone = await repo.kinds_of(
            [change.undoes_id for change in changes if change.undoes_id]
        )
        items = []
        for change, row in zip(changes, rows):
            kind = undone.get(change.undoes_id, change.kind)
            count, approved = asked.get((change.connection_id, kind), (0, 0))
            items.append(
                _item(
                    "change",
                    change.asked_at,
                    change=row,
                    asked={
                        "kind": kind,
                        "count": count,
                        "approved": approved,
                        "since": since.isoformat(),
                    },
                )
            )
        return items


class NotifiedSource:
    """what the reader's connections did at act and notify lately, undoable
    as on the changes page."""

    section: Section = "notified"
    needs_change = True

    async def items(
        self, session: AsyncSession, reader: Reader, now: datetime
    ) -> list[dict]:
        changes = await ChangeRepository(session, reader.tenant_id).notified_for(
            reader.user_id, now - NOTIFIED_WITHIN, NOTIFIED_MAX
        )
        rows = await workspace_rows(
            session, reader.tenant_id, [[change] for change in changes]
        )
        return [
            _item("change", change.created_at, change=row)
            for change, row in zip(changes, rows)
        ]


class SafetyPauseSource:
    """the workspace's loops qbrix paused that no one has resumed yet."""

    section: Section = "alerts"
    needs_change = False

    async def items(
        self, session: AsyncSession, reader: Reader, now: datetime
    ) -> list[dict]:
        loops = await LoopRepository(session, reader.tenant_id).with_states(("paused",))
        latest = await ChangeRepository(session, reader.tenant_id).latest_for_each(
            "loop", [loop.id for loop in loops], kinds=ALERT_KINDS
        )
        items = []
        for loop in loops:
            pause = latest.get(loop.id)
            if is_safety_pause(pause):
                items.append(
                    _item(
                        SAFETY_PAUSE,
                        pause.created_at,
                        loop={"id": loop.id, "key": loop.key, "name": loop.name},
                        alert=opened(pause),
                    )
                )
        return items


SOURCES: tuple[Source, ...] = (WaitingSource(), NotifiedSource(), SafetyPauseSource())
