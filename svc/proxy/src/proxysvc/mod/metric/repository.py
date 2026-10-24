from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qbrixcore.engine import MetricType
from qbrixcore.engine import ScoreRange
from qbrixstore.postgres.models import Metric
from qbrixstore.postgres.models import MetricVersion


class MetricRepository:

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def create(
        self,
        name: str,
        metric_type: MetricType,
        score_range: ScoreRange | None,
        semantic: str,
        window_sec: int,
        created_by: str,
    ) -> Metric:
        metric = Metric(
            tenant_id=self._tenant_id,
            name=name,
            type=metric_type.value,
            score_lo=score_range.lo if score_range else None,
            score_hi=score_range.hi if score_range else None,
            created_by=created_by,
        )
        metric.versions.append(
            MetricVersion(
                major=1,
                minor=0,
                semantic=semantic,
                window_sec=window_sec,
                created_by=created_by,
            )
        )
        self._session.add(metric)
        await self._session.flush()
        return metric

    async def get(self, metric_id: str) -> Metric | None:
        return await self._one(Metric.id == metric_id)

    async def get_by_name(self, name: str) -> Metric | None:
        return await self._one(Metric.name == name)

    async def resolve(self, ref: str) -> Metric | None:
        """a metric by its id, else by its name."""
        return await self.get(ref) or await self.get_by_name(ref)

    async def list(self) -> list[Metric]:
        stmt = (
            select(Metric)
            .options(selectinload(Metric.versions))
            .where(Metric.tenant_id == self._tenant_id)
            .order_by(Metric.name)
        )
        response = await self._session.execute(stmt)
        return list(response.scalars().all())

    async def delete(self, metric: Metric) -> None:
        await self._session.delete(metric)
        await self._session.flush()

    async def _one(self, *where) -> Metric | None:
        stmt = (
            select(Metric)
            .options(selectinload(Metric.versions))
            .where(Metric.tenant_id == self._tenant_id, *where)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()
