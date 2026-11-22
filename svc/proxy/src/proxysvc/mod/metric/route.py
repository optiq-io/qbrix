from __future__ import annotations

import redis.asyncio as aioredis
from pydantic import BaseModel

from qbrixstore.postgres.models import Metric
from qbrixstore.postgres.session import get_session

from proxysvc.config import ProxySettings
from proxysvc.core.cache.layered import TwoTierCache
from proxysvc.mod.metric.repository import MetricRepository

_NAMESPACE = "qbrix:tenant"


class RouteMetric(BaseModel):
    """what the request path needs of a metric: how to check a value, and
    the version and window new decisions open under."""

    id: str
    name: str
    version: str
    type: str
    score_lo: float | None = None
    score_hi: float | None = None
    window_ms: int


def route_metric_of(metric: Metric) -> RouteMetric:
    version = metric.versions[-1]
    return RouteMetric(
        id=metric.id,
        name=metric.name,
        version=f"{version.major}.{version.minor}",
        type=metric.type,
        score_lo=metric.score_lo,
        score_hi=metric.score_hi,
        window_ms=version.window_sec * 1000,
    )


class MetricRouteCache:
    """a metric by the name code sends, read through to postgres.

    a metric's type and range never change, and decisions are sealed by the
    version they opened under, so a version a few seconds stale is harmless.
    a deleted metric is dropped so its name can be reused.
    """

    def __init__(self, redis: aioredis.Redis, settings: ProxySettings):
        self._tier = TwoTierCache[RouteMetric](
            redis=redis,
            model=RouteMetric,
            namespace=_NAMESPACE,
            l1_maxsize=settings.experiment_cache_maxsize,
            l1_ttl=settings.experiment_cache_ttl,
            l2_ttl=settings.experiment_cache_ttl,
        )

    async def get(self, tenant_id: str, name: str) -> RouteMetric | None:
        cached = await self._tier.get(tenant_id, "metric", "name", name)
        if cached is not None:
            return cached
        async with get_session() as session:
            metric = await MetricRepository(session, tenant_id).get_by_name(name)
            if metric is None:
                return None
            route = route_metric_of(metric)
        await self._tier.set(tenant_id, "metric", "name", name, value=route)
        return route

    async def get_by_id(self, tenant_id: str, metric_id: str) -> RouteMetric | None:
        """a metric by its id: the one a decision was made under, which may
        no longer be its loop's."""
        cached = await self._tier.get(tenant_id, "metric", "id", metric_id)
        if cached is not None:
            return cached
        async with get_session() as session:
            metric = await MetricRepository(session, tenant_id).get(metric_id)
            if metric is None:
                return None
            route = route_metric_of(metric)
        await self._tier.set(tenant_id, "metric", "id", metric_id, value=route)
        return route

    async def drop(self, tenant_id: str, name: str, metric_id: str) -> None:
        await self._tier.delete(tenant_id, "metric", "name", name)
        await self._tier.delete(tenant_id, "metric", "id", metric_id)
