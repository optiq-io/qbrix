"""per-minute counts of a loop's answered select calls, by reason."""

from __future__ import annotations

import pytest

from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import SELECT_HEALTH_TTL_SEC
from qbrixstore.redis.health import LoopSelectReason

pytestmark = pytest.mark.integration

TENANT = "t1"
LOOP = "loop-1"
NOW = 29_000_000


@pytest.fixture
async def store(redis_server) -> RedisClient:
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


async def test_record_writes_the_reason_key_with_a_ttl(store):
    await store.record_loop_select(TENANT, LOOP, LoopSelectReason.DRAFT, minute=NOW)

    key = f"qbrix:tenant:{TENANT}:health:loop_select:{LOOP}:{NOW}:draft"
    assert await store.client.get(key) == "1"
    assert 0 < await store.client.ttl(key) <= SELECT_HEALTH_TTL_SEC


async def test_counts_by_reason_inside_the_window(store):
    for minute in (NOW - 2, NOW - 1, NOW):
        await store.record_loop_select(
            TENANT, LOOP, LoopSelectReason.LIVE, minute=minute
        )
    await store.record_loop_select(TENANT, LOOP, LoopSelectReason.PAUSED, minute=NOW)
    await store.record_loop_select(TENANT, LOOP, LoopSelectReason.LIVE, minute=NOW - 10)

    counts = await store.loop_selects(TENANT, LOOP, window_minutes=3, now_minute=NOW)

    assert counts == {"live": 3, "draft": 0, "paused": 1}


async def test_another_loop_is_counted_apart(store):
    await store.record_loop_select(TENANT, "other", LoopSelectReason.LIVE, minute=NOW)

    counts = await store.loop_selects(TENANT, LOOP, window_minutes=1, now_minute=NOW)

    assert counts == {"live": 0, "draft": 0, "paused": 0}
