"""hourly counts of a loop's answered select calls, whatever their reason,
and since when qbrix has counted without a gap."""

from __future__ import annotations

import pytest

from qbrixstore.redis.client import COUNTING_KEY
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import COUNTING_GAP_MS
from qbrixstore.redis.health import LOOP_CALLS_TTL_SEC
from qbrixstore.redis.health import LoopSelectReason

pytestmark = pytest.mark.integration

TENANT = "t1"
LOOP = "loop-1"
HOUR = 480_000
MINUTE = HOUR * 60
NOW_MS = MINUTE * 60_000


@pytest.fixture
async def store(redis_server) -> RedisClient:
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


async def test_every_reason_counts_in_the_hour_for_a_day_and_more(store):
    for reason in (LoopSelectReason.LIVE, LoopSelectReason.OUTSIDE_DELIVERY):
        await store.record_loop_select(TENANT, LOOP, reason, minute=MINUTE + 5)
    await store.record_loop_select(
        TENANT, LOOP, LoopSelectReason.COMMITTED, minute=MINUTE + 59
    )

    key = f"qbrix:tenant:{TENANT}:health:loop_calls:{LOOP}:{HOUR}"
    assert await store.client.get(key) == "3"
    assert 24 * 60 * 60 < await store.client.ttl(key) <= LOOP_CALLS_TTL_SEC


async def test_reads_many_loops_and_hours_in_one_call(store):
    await store.record_loop_select(TENANT, LOOP, LoopSelectReason.LIVE, minute=MINUTE)
    await store.record_loop_select(
        TENANT, LOOP, LoopSelectReason.LIVE, minute=MINUTE - 25 * 60
    )
    await store.record_loop_select(
        TENANT, "other", LoopSelectReason.LIVE, minute=MINUTE
    )

    counts = await store.loops_hourly_calls(
        TENANT, [LOOP, "other", "quiet"], (HOUR - 25, HOUR - 1, HOUR)
    )

    assert counts == {
        LOOP: {HOUR - 25: 1, HOUR - 1: 0, HOUR: 1},
        "other": {HOUR - 25: 0, HOUR - 1: 0, HOUR: 1},
        "quiet": {HOUR - 25: 0, HOUR - 1: 0, HOUR: 0},
    }
    assert await store.loops_hourly_calls(TENANT, [], (HOUR,)) == {}


async def test_counting_since_holds_across_short_gaps_and_restarts_after_long(
    store,
):
    assert await store.counting_since(NOW_MS) == NOW_MS
    assert await store.counting_since(NOW_MS + COUNTING_GAP_MS) == NOW_MS

    later = NOW_MS + 2 * COUNTING_GAP_MS + 1
    assert await store.counting_since(later) == later
    assert 0 < await store.client.ttl(COUNTING_KEY) <= LOOP_CALLS_TTL_SEC
