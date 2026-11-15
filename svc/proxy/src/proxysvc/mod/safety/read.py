from __future__ import annotations

from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.session import get_session

from proxysvc.core.error import LoopNotFoundError
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.milestone.entry import LoopName
from proxysvc.mod.people import People
from proxysvc.mod.safety.entry import alert_entry
from proxysvc.mod.safety.repository import AlertRepository

OPEN_LIMIT = 50


async def read_alerts(
    session: AsyncSession,
    tenant_id: str,
    *,
    loop_ids: Collection[str] | None,
    open: bool | None,
    limit: int,
) -> list[dict]:
    """alerts as entries, newest first, with loop names as they are now."""
    found = await AlertRepository(session, tenant_id).list(
        loop_ids=loop_ids, open=open, limit=limit
    )
    names = await LoopRepository(session, tenant_id).names(
        {alert.loop_id for alert in found}
    )
    people = await People.load(
        session,
        tenant_id,
        (alert.resolved_user_id for alert in found if alert.resolved_kind != "qbrix"),
    )
    return [
        alert_entry(alert, LoopName(*names[alert.loop_id]), people)
        for alert in found
        if alert.loop_id in names
    ]


class AlertReadService:
    """the record of every alert, for the inbox, the header and agents."""

    async def list_alerts(
        self,
        tenant_id: str,
        *,
        loop: str | None = None,
        open: bool | None = None,
        limit: int,
    ) -> dict:
        async with get_session() as session:
            loop_ids = None
            if loop is not None:
                found = await LoopRepository(session, tenant_id).resolve(loop)
                if found is None:
                    raise LoopNotFoundError(f"no loop with the key or id {loop!r}")
                loop_ids = [found.id]
            alerts = await read_alerts(
                session, tenant_id, loop_ids=loop_ids, open=open, limit=limit
            )
        return {"alerts": alerts}
