from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Literal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.service import workspace_rows
from proxysvc.mod.github.mention import mention_entry
from proxysvc.mod.github.repository import MentionRepository
from proxysvc.mod.safety.entry import kind_of
from proxysvc.mod.safety.read import OPEN_LIMIT
from proxysvc.mod.safety.read import RECOVERED_SHOWN
from proxysvc.mod.safety.read import read_alerts

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


def _item(kind: str, at: datetime, **parts: Any) -> dict:
    return {
        "kind": kind,
        "at": at.isoformat(),
        "change": None,
        "asked": None,
        "loop": None,
        "alert": None,
        "pull_request": None,
        "pieces": None,
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


def _alert_item(alert: dict, at: str) -> dict:
    return _item(
        kind_of(alert["signal"]),
        datetime.fromisoformat(at),
        loop=alert["loop"],
        alert=alert,
    )


class OpenAlertSource:
    """the workspace's open alerts, safety pauses and warnings alike, for
    every member."""

    section: Section = "alerts"
    needs_change = False

    async def items(
        self, session: AsyncSession, reader: Reader, now: datetime
    ) -> list[dict]:
        alerts = await read_alerts(
            session, reader.tenant_id, loop_ids=None, open=True, limit=OPEN_LIMIT
        )
        return [_alert_item(alert, alert["opened_at"]) for alert in alerts]


class RecoveredAlertSource:
    """alerts that ended lately, kept for a week marked recovered, for every
    member."""

    section: Section = "notified"
    needs_change = False

    async def items(
        self, session: AsyncSession, reader: Reader, now: datetime
    ) -> list[dict]:
        alerts = await read_alerts(
            session,
            reader.tenant_id,
            loop_ids=None,
            open=False,
            limit=NOTIFIED_MAX,
            since=now - RECOVERED_SHOWN,
            newest="resolved",
        )
        return [_alert_item(alert, alert["resolved_at"]) for alert in alerts]


class LaunchSource:
    """the reader's drafts whose pull request merged, each suggesting its
    launch until it launches or is deleted. a merge is not a deploy, so it
    only suggests."""

    section: Section = "suggestions"
    needs_change = False

    async def items(
        self, session: AsyncSession, reader: Reader, now: datetime
    ) -> list[dict]:
        drafts = await MentionRepository(session, reader.tenant_id).merged_drafts(
            reader.user_id
        )
        return [
            _item(
                "launch",
                mention.merged_at or mention.at,
                loop={"id": loop.id, "key": loop.key, "name": loop.name},
                pull_request=mention_entry(mention),
                pieces=[
                    {"kind": "text", "text": "The code for "},
                    {"kind": "loop", "name": loop.name},
                    {"kind": "text", "text": " is merged. Launch it?"},
                ],
            )
            for loop, mention in drafts
        ]


SOURCES: tuple[Source, ...] = (
    WaitingSource(),
    NotifiedSource(),
    OpenAlertSource(),
    RecoveredAlertSource(),
    LaunchSource(),
)
