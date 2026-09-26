from __future__ import annotations

from typing import Generic
from typing import TypeVar

import redis.asyncio as aioredis
from cachebox import TTLCache
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class TwoTierCache(Generic[T]):
    """generic l1 (in-memory ttl) → l2 (redis) cache for pydantic models.

    l1 is microsecond access; l2 is millisecond access and serves as the
    shared source of truth across horizontally-scaled proxy replicas.

    key format: "<namespace>:<part1>:<part2>:..."
    """

    def __init__(
        self,
        *,
        redis: aioredis.Redis,
        model: type[T],
        namespace: str,
        l1_maxsize: int,
        l1_ttl: float,
        l2_ttl: float,
    ) -> None:
        self._redis = redis
        self._model = model
        self._namespace = namespace
        self._l2_ttl = l2_ttl
        self._l1: TTLCache = TTLCache(maxsize=l1_maxsize, ttl=l1_ttl)

    def _key(self, *parts: str) -> str:
        return ":".join((self._namespace, *parts))

    async def get(self, *parts: str) -> T | None:
        key = self._key(*parts)
        if (hit := self._l1.get(key)) is not None:
            return hit
        raw = await self._redis.get(key)
        if raw is None:
            return None
        value = self._model.model_validate_json(raw)
        self._l1[key] = value
        return value

    async def set(self, *parts: str, value: T) -> None:
        key = self._key(*parts)
        await self._redis.set(key, value.model_dump_json(), ex=int(self._l2_ttl))
        self._l1[key] = value

    async def delete(self, *parts: str) -> None:
        key = self._key(*parts)
        await self._redis.delete(key)
        self._l1.pop(key, None)

    def invalidate(self, *parts: str) -> None:
        self._l1.pop(self._key(*parts), None)
