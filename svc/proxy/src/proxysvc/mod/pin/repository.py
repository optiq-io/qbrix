from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import Metric
from qbrixstore.postgres.models import Pin

LOOP = "loop"
METRIC = "metric"

_TARGET = {LOOP: Loop, METRIC: Metric}


class PinRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list(self, tenant_id: str, user_id: str) -> list[Pin]:
        stmt = (
            select(Pin)
            .where(Pin.tenant_id == tenant_id, Pin.user_id == user_id)
            .order_by(Pin.position, Pin.created_at)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def get(self, user_id: str, kind: str, ref: str) -> Pin | None:
        stmt = select(Pin).where(
            Pin.user_id == user_id, Pin.kind == kind, Pin.ref == ref
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, tenant_id: str, user_id: str, kind: str, ref: str) -> Pin:
        last = select(func.max(Pin.position)).where(Pin.user_id == user_id)
        position = (await self._session.execute(last)).scalar_one()
        pin = Pin(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=kind,
            ref=ref,
            position=0 if position is None else position + 1,
        )
        self._session.add(pin)
        await self._session.flush()
        return pin

    async def delete(self, user_id: str, kind: str, ref: str) -> None:
        await self._session.execute(
            delete(Pin).where(Pin.user_id == user_id, Pin.kind == kind, Pin.ref == ref)
        )

    async def target_exists(self, tenant_id: str, kind: str, ref: str) -> bool:
        model = _TARGET[kind]
        stmt = select(model.id).where(model.tenant_id == tenant_id, model.id == ref)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def loops(self, tenant_id: str, ids: Iterable[str]) -> dict[str, Loop]:
        stmt = select(Loop).where(Loop.tenant_id == tenant_id, Loop.id.in_(ids))
        return {loop.id: loop for loop in (await self._session.execute(stmt)).scalars()}

    async def metrics(self, tenant_id: str, ids: Iterable[str]) -> dict[str, Metric]:
        stmt = select(Metric).where(Metric.tenant_id == tenant_id, Metric.id.in_(ids))
        return {
            metric.id: metric
            for metric in (await self._session.execute(stmt)).scalars()
        }
