from __future__ import annotations

import redis.asyncio as aioredis
from pydantic import BaseModel
from pydantic import ConfigDict

from qbrixcore.context_schema import ContextSchema
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop

from proxysvc.config import ProxySettings
from proxysvc.core.cache.layered import TwoTierCache
from proxysvc.mod.loop.delivery import EVERYONE
from proxysvc.mod.loop.delivery import Delivery
from proxysvc.mod.loop.delivery import delivery_of
from proxysvc.mod.loop.serialize import option_to_dict

_NAMESPACE = "qbrix:tenant"


class RouteOption(BaseModel):
    id: str
    key: str
    name: str
    config: dict


class RouteCycle(BaseModel):
    """context is the schema the cycle's engine learns from, if it learns
    from any; select encodes properties with it."""

    id: str
    number: int
    context: ContextSchema | None = None


def _route_cycle(cycle: Cycle) -> RouteCycle:
    return RouteCycle(
        id=cycle.id,
        number=cycle.number,
        context=(
            ContextSchema.model_validate(cycle.context_schema)
            if cycle.context_schema
            else None
        ),
    )


class RouteMetric(BaseModel):
    id: str
    version: str
    type: str
    score_lo: float | None = None
    score_hi: float | None = None
    window_ms: int


class LoopRoute(BaseModel):
    """what select needs to answer for a loop, without reading postgres.

    the options are the current cycle's, in the order its arms are served,
    or the loop's own while it is a draft. committed is the index of the
    option a committed loop serves. a route written before loops had a
    delivery reads as deciding for everyone.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    key: str
    state: str
    cycle: RouteCycle | None
    options: list[RouteOption]
    fallback: RouteOption
    metric: RouteMetric
    committed: int | None = None
    delivery: Delivery = EVERYONE


def route_of(loop: Loop) -> LoopRoute:
    cycle = loop.cycles[-1] if loop.cycles else None
    options = (
        cycle.options if cycle else [option_to_dict(option) for option in loop.options]
    )
    keys = [option["key"] for option in options]
    version = loop.metric.versions[-1]
    return LoopRoute(
        id=loop.id,
        key=loop.key,
        state=loop.state,
        cycle=_route_cycle(cycle) if cycle else None,
        options=options,
        committed=(
            keys.index(loop.committed_key) if loop.committed_key is not None else None
        ),
        fallback=next(o for o in options if o["key"] == loop.fallback_key),
        delivery=delivery_of(loop.delivery),
        metric=RouteMetric(
            id=loop.metric.id,
            version=f"{version.major}.{version.minor}",
            type=loop.metric.type,
            score_lo=loop.metric.score_lo,
            score_hi=loop.metric.score_hi,
            window_ms=version.window_sec * 1000,
        ),
    )


class LoopRouteCache:
    """a loop's route under its id and its key, read through a short l1.

    the record in redis never expires: it is the only thing select reads, so
    it is written on every loop write and removed when the loop is.
    """

    def __init__(self, redis: aioredis.Redis, settings: ProxySettings):
        self._redis = redis
        self._tier = TwoTierCache[LoopRoute](
            redis=redis,
            model=LoopRoute,
            namespace=_NAMESPACE,
            l1_maxsize=settings.experiment_cache_maxsize,
            l1_ttl=settings.experiment_cache_ttl,
            l2_ttl=settings.experiment_cache_ttl,
        )

    async def get(self, tenant_id: str, ref: str) -> LoopRoute | None:
        """a route by the loop's id, else by its key."""
        return await self._tier.get(
            tenant_id, "loop", "id", ref
        ) or await self._tier.get(tenant_id, "loop", "key", ref)

    async def put(
        self, tenant_id: str, route: LoopRoute, old_key: str | None = None
    ) -> None:
        raw = route.model_dump_json()
        pipe = self._redis.pipeline(transaction=True)
        # noinspection PyAsyncCall
        pipe.set(self._key(tenant_id, "id", route.id), raw)
        # noinspection PyAsyncCall
        pipe.set(self._key(tenant_id, "key", route.key), raw)
        if old_key is not None and old_key != route.key:
            # noinspection PyAsyncCall
            pipe.delete(self._key(tenant_id, "key", old_key))
        await pipe.execute()
        self._forget(tenant_id, route.id, route.key, old_key)

    async def drop(self, tenant_id: str, loop_id: str, key: str) -> None:
        await self._redis.delete(
            self._key(tenant_id, "id", loop_id), self._key(tenant_id, "key", key)
        )
        self._forget(tenant_id, loop_id, key)

    def _forget(self, tenant_id: str, loop_id: str, *keys: str | None) -> None:
        self._tier.invalidate(tenant_id, "loop", "id", loop_id)
        for key in keys:
            if key is not None:
                self._tier.invalidate(tenant_id, "loop", "key", key)

    @staticmethod
    def _key(tenant_id: str, kind: str, ref: str) -> str:
        return ":".join((_NAMESPACE, tenant_id, "loop", kind, ref))
