from __future__ import annotations

from collections.abc import Collection
from collections.abc import Sequence

from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import LoopOption
from qbrixstore.postgres.models import Metric

from proxysvc.core.cursor import Position

_LOADS = (
    selectinload(Loop.options),
    selectinload(Loop.cycles).selectinload(Cycle.metric_version),
    selectinload(Loop.metric).selectinload(Metric.versions),
)


class LoopRepository:

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def create(
        self,
        *,
        key: str,
        name: str,
        purpose: str,
        metric: Metric,
        engine: str,
        owner_user_id: str,
        fallback_key: str,
        options: list[LoopOption],
    ) -> Loop:
        loop = Loop(
            tenant_id=self._tenant_id,
            key=key,
            name=name,
            purpose=purpose,
            metric_id=metric.id,
            engine=engine,
            state="draft",
            owner_user_id=owner_user_id,
            fallback_key=fallback_key,
            options=options,
        )
        self._session.add(loop)
        await self._session.flush()
        return await self.get(loop.id)

    async def get(self, loop_id: str) -> Loop | None:
        return await self._one(Loop.id == loop_id)

    async def get_by_key(self, key: str) -> Loop | None:
        return await self._one(Loop.key == key)

    async def names(self, loop_ids: Collection[str]) -> dict[str, tuple[str, str]]:
        """each loop's key and name, in one query."""
        if not loop_ids:
            return {}
        stmt = select(Loop.id, Loop.key, Loop.name).where(
            Loop.tenant_id == self._tenant_id, Loop.id.in_(loop_ids)
        )
        rows = (await self._session.execute(stmt)).all()
        return {row.id: (row.key, row.name) for row in rows}

    async def resolve(self, ref: str) -> Loop | None:
        """a loop by its id, else by its key."""
        return await self.get(ref) or await self.get_by_key(ref)

    async def keys_from(self, base: str) -> set[str]:
        """the workspace's keys that a key generated from base could collide with."""
        stmt = select(Loop.key).where(
            Loop.tenant_id == self._tenant_id,
            Loop.key.startswith(base, autoescape=True),
        )
        response = await self._session.execute(stmt)
        return set(response.scalars().all())

    async def first_using_metric(self, metric_id: str) -> Loop | None:
        stmt = (
            select(Loop)
            .where(Loop.tenant_id == self._tenant_id, Loop.metric_id == metric_id)
            .order_by(Loop.created_at)
            .limit(1)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def using_metrics(self, metric_ids: Sequence[str]) -> dict[str, list[Loop]]:
        """the loops using each metric, oldest first."""
        if not metric_ids:
            return {}
        stmt = (
            select(Loop)
            .where(Loop.tenant_id == self._tenant_id, Loop.metric_id.in_(metric_ids))
            .order_by(Loop.created_at, Loop.id)
        )
        response = await self._session.execute(stmt)
        using: dict[str, list[Loop]] = {}
        for loop in response.scalars().all():
            using.setdefault(loop.metric_id, []).append(loop)
        return using

    async def page(
        self, states: Sequence[str], before: Position | None, limit: int
    ) -> list[Loop]:
        """newest first, from just after before; up to limit loops."""
        stmt = select(Loop).options(*_LOADS).where(Loop.tenant_id == self._tenant_id)
        if states:
            stmt = stmt.where(Loop.state.in_(states))
        if before is not None:
            created_at, loop_id = before
            stmt = stmt.where(
                or_(
                    Loop.created_at < created_at,
                    and_(Loop.created_at == created_at, Loop.id < loop_id),
                )
            )
        stmt = stmt.order_by(Loop.created_at.desc(), Loop.id.desc()).limit(limit)
        response = await self._session.execute(stmt)
        return list(response.scalars().all())

    async def live_cycles(self, cycle_ids: Sequence[str]) -> list[tuple[Loop, str]]:
        """the live loops whose running cycle is one of cycle_ids, with it."""
        stmt = (
            select(Loop, Cycle.id)
            .join(Cycle, Cycle.loop_id == Loop.id)
            .where(
                Loop.tenant_id == self._tenant_id,
                Loop.state == "live",
                Cycle.id.in_(cycle_ids),
                Cycle.ended_at.is_(None),
            )
        )
        response = await self._session.execute(stmt)
        return [(loop, cycle_id) for loop, cycle_id in response.all()]

    async def reload(self, loop: Loop) -> Loop:
        """the loop as written, with its options and cycles read back."""
        await self._session.flush()
        return await self.get(loop.id)

    async def transition(self, loop_id: str, *, from_state: str, **values) -> bool:
        """write values only while the loop is still in from_state: of two
        concurrent transitions, one moves it and the other finds it moved."""
        result = await self._session.execute(
            update(Loop)
            .where(
                Loop.tenant_id == self._tenant_id,
                Loop.id == loop_id,
                Loop.state == from_state,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    async def delete(self, loop: Loop) -> None:
        await self._session.delete(loop)
        await self._session.flush()

    async def _one(self, *where) -> Loop | None:
        stmt = (
            select(Loop)
            .options(*_LOADS)
            .where(Loop.tenant_id == self._tenant_id, *where)
            .execution_options(populate_existing=True)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()
