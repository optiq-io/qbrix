from __future__ import annotations

import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import BaseModel

from proxysvc.core.cache.layered import TwoTierCache

pytestmark = pytest.mark.unit


class _Entry(BaseModel):
    id: str
    name: str


def _cache(redis: FakeRedis) -> TwoTierCache[_Entry]:
    return TwoTierCache[_Entry](
        redis=redis,
        model=_Entry,
        namespace="test",
        l1_maxsize=16,
        l1_ttl=30.0,
        l2_ttl=30.0,
    )


class TestTwoTierCache:
    async def test_reads_back_what_it_wrote(self):
        redis = FakeRedis(decode_responses=True)
        await _cache(redis).set("a", value=_Entry(id="1", name="one"))

        assert await _cache(redis).get("a") == _Entry(id="1", name="one")

    async def test_an_entry_in_an_older_shape_is_a_miss(self):
        redis = FakeRedis(decode_responses=True)
        await redis.set("test:a", '{"id": "1"}')

        assert await _cache(redis).get("a") is None
