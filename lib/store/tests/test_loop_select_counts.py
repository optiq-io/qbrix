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
    await store.record_loop_select(
        TENANT, LOOP, LoopSelectReason.COMMITTED, minute=NOW - 1
    )
    await store.record_loop_select(TENANT, LOOP, LoopSelectReason.LIVE, minute=NOW - 10)

    counts = await store.loop_selects(TENANT, LOOP, window_minutes=3, now_minute=NOW)

    assert counts == {"live": 3, "committed": 1, "draft": 0, "paused": 1}


async def test_another_loop_is_counted_apart(store):
    await store.record_loop_select(TENANT, "other", LoopSelectReason.LIVE, minute=NOW)

    counts = await store.loop_selects(TENANT, LOOP, window_minutes=1, now_minute=NOW)

    assert counts == {"live": 0, "committed": 0, "draft": 0, "paused": 0}


async def test_many_loops_are_counted_apart_in_one_read(store):
    await store.record_loop_select(TENANT, LOOP, LoopSelectReason.LIVE, minute=NOW)
    await store.record_loop_select(TENANT, "other", LoopSelectReason.DRAFT, minute=NOW)

    counts = await store.loops_selects(
        TENANT, [LOOP, "other", "quiet"], window_minutes=1, now_minute=NOW
    )

    assert counts == {
        LOOP: {"live": 1, "committed": 0, "draft": 0, "paused": 0},
        "other": {"live": 0, "committed": 0, "draft": 1, "paused": 0},
        "quiet": {"live": 0, "committed": 0, "draft": 0, "paused": 0},
    }


async def test_no_loops_reads_nothing(store):
    assert await store.loops_selects(TENANT, [], window_minutes=1) == {}
