from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
from datetime import datetime
from typing import Awaitable
from typing import TypeVar

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.postgres.session import get_session

from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import MetricNotFoundError
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.metric.repository import MetricRepository
from proxysvc.mod.milestone.entry import LoopName
from proxysvc.mod.milestone.entry import entry
from proxysvc.mod.milestone.entry import fold

T = TypeVar("T")

Read = Callable[[Callable[[ClickHouseClient], T]], Awaitable[T]]


class MilestoneService:
    """what a workspace's loops reached, read from the ledger and written into
    sentences here, so names are always current and every reader agrees."""

    def __init__(self, read: Read):
        self._read = read

    async def list_events(
        self,
        tenant_id: str,
        *,
        loop: str | None = None,
        metric: str | None = None,
        kinds: Sequence[str] = (),
        since: datetime | None = None,
        limit: int,
    ) -> dict:
        async with get_session() as session:
            loop_ids = await self._narrow(session, tenant_id, loop, metric)
        if loop_ids == []:
            return {"events": []}

        found = await self._read(
            lambda ch: ch.query_milestones(
                tenant_id,
                loop_ids=loop_ids,
                kinds=list(kinds) or None,
                since_ms=int(since.timestamp() * 1000) if since else None,
                limit=limit,
            )
        )

        async with get_session() as session:
            loops = LoopRepository(session, tenant_id)
            names = await loops.names({event.loop_id for event in found})
            options = await loops.cycle_option_names(
                {event.cycle_id for event in found if event.cycle_id}
            )

        events = []
        for group in fold(found):
            first = group[0]
            named = names.get(first.loop_id)
            if named is None:
                continue
            made = entry(
                group,
                LoopName(key=named[0], name=named[1]),
                options.get(first.cycle_id, []),
            )
            if made is not None:
                events.append(made)
        return {"events": events}

    @staticmethod
    async def _narrow(
        session, tenant_id: str, loop: str | None, metric: str | None
    ) -> list[str] | None:
        """the loops the filters allow, or none for the whole workspace."""
        allowed: list[str] | None = None
        if loop is not None:
            named = await LoopRepository(session, tenant_id).resolve(loop)
            if named is None:
                raise LoopNotFoundError(loop)
            allowed = [named.id]
        if metric is not None:
            found = await MetricRepository(session, tenant_id).resolve(metric)
            if found is None:
                raise MetricNotFoundError(metric)
            using = await LoopRepository(session, tenant_id).using_metrics([found.id])
            ids = [used.id for used in using.get(found.id, [])]
            allowed = ids if allowed is None else [i for i in allowed if i in ids]
        return allowed
