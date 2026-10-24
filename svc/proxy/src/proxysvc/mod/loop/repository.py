from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import LoopOption
from qbrixstore.postgres.models import Metric


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

    async def reload(self, loop: Loop) -> Loop:
        """the loop as written, with its options and cycles read back."""
        await self._session.flush()
        return await self.get(loop.id)

    async def delete(self, loop: Loop) -> None:
        await self._session.delete(loop)
        await self._session.flush()

    async def _one(self, *where) -> Loop | None:
        stmt = (
            select(Loop)
            .options(
                selectinload(Loop.options),
                selectinload(Loop.cycles).selectinload(Cycle.metric_version),
                selectinload(Loop.metric).selectinload(Metric.versions),
            )
            .where(Loop.tenant_id == self._tenant_id, *where)
            .execution_options(populate_existing=True)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()
