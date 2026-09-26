from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qbrixstore.postgres.models import Arm
from qbrixstore.postgres.models import Pool


class PoolRepository:

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def create(self, name: str, arms: list[dict]) -> Pool:
        pool = Pool(name=name, tenant_id=self._tenant_id)
        for i, arm_data in enumerate(arms):
            arm = Arm(
                name=arm_data["name"], index=i, metadata_=arm_data.get("metadata", {})
            )
            pool.arms.append(arm)
        self._session.add(pool)
        await self._session.flush()
        return pool

    async def get(self, pool_id: str) -> Pool | None:
        stmt = (
            select(Pool)
            .options(selectinload(Pool.arms))
            .where(Pool.id == pool_id, Pool.tenant_id == self._tenant_id)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Pool | None:
        stmt = (
            select(Pool)
            .options(selectinload(Pool.arms))
            .where(Pool.name == name, Pool.tenant_id == self._tenant_id)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def update(self, pool_id: str, **kwargs) -> Pool | None:
        pool = await self.get(pool_id)
        if pool is None:
            return None

        for key, value in kwargs.items():
            if hasattr(pool, key) and value is not None:
                setattr(pool, key, value)

        await self._session.flush()
        return pool

    async def delete(self, pool_id: str) -> bool:
        pool = await self.get(pool_id)
        if pool is None:
            return False
        await self._session.delete(pool)
        await self._session.flush()
        return True

    async def list(self, limit: int = 100, offset: int = 0) -> list[Pool]:
        stmt = (
            select(Pool)
            .options(selectinload(Pool.arms))
            .where(Pool.tenant_id == self._tenant_id)
            .order_by(Pool.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        response = await self._session.execute(stmt)
        return list(response.scalars().all())
