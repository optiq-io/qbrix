from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from datetime import timezone

from qbrixstore.postgres.session import get_session

from proxysvc.mod.auth.scope import ROLE_SCOPES
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.inbox import source
from proxysvc.mod.inbox.source import Reader
from proxysvc.mod.inbox.source import Section

NEWEST_FIRST: dict[Section, bool] = {
    "waiting": False,
    "notified": True,
    "alerts": False,
    "suggestions": True,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reader(tenant_id: str, user_id: str, role: str) -> Reader:
    return Reader(
        tenant_id=tenant_id,
        user_id=user_id,
        can_change="loop:write" in ROLE_SCOPES.get(role, ()),
    )


class InboxService:
    """a person's inbox, read from what is already stored: nothing is kept
    per person, so an answered change or a resumed loop leaves it at once.

    each kind of item comes from a source in source.SOURCES; a section holds
    whatever its sources give, in the section's order.
    """

    def __init__(self, *, clock: Callable[[], datetime] = _now):
        self._clock = clock

    async def read(self, tenant_id: str, user_id: str, role: str) -> dict:
        reader = _reader(tenant_id, user_id, role)
        now = self._clock()
        sections: dict[Section, list[dict]] = {name: [] for name in NEWEST_FIRST}
        async with get_session() as session:
            for each in source.SOURCES:
                if each.needs_change and not reader.can_change:
                    continue
                sections[each.section] += await each.items(session, reader, now)
        for name, items in sections.items():
            items.sort(key=lambda item: item["at"], reverse=NEWEST_FIRST[name])
        return sections

    async def count(self, tenant_id: str, user_id: str, role: str) -> dict:
        """what waits on the person, without reading the items."""
        if not _reader(tenant_id, user_id, role).can_change:
            return {"waiting": 0}
        async with get_session() as session:
            waiting = await ChangeRepository(session, tenant_id).count_waiting_for(
                user_id
            )
        return {"waiting": waiting}
