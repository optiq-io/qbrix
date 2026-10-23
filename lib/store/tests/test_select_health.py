"""per-minute select outcome counters and the windowed reader."""

from __future__ import annotations

import pytest

from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import SELECT_HEALTH_TTL_SEC
from qbrixstore.redis.health import SelectErrorReason
from qbrixstore.redis.health import SelectHealth
from qbrixstore.redis.health import SelectOutcome

pytestmark = pytest.mark.integration

TENANT = "t1"
EXPERIMENT = "exp"
NOW = 29_000_000


@pytest.fixture
async def store(redis_server) -> RedisClient:
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


async def test_record_writes_the_outcome_key_with_a_ttl(store):
    await store.record_select(TENANT, EXPERIMENT, SelectOutcome.OK, minute=NOW)

    key = f"qbrix:tenant:{TENANT}:health:select:{EXPERIMENT}:{NOW}:ok"
    assert await store.client.get(key) == "1"
    assert 0 < await store.client.ttl(key) <= SELECT_HEALTH_TTL_SEC


async def test_record_writes_the_reason_key_beside_the_outcome(store):
    await store.record_select(
        TENANT,
        EXPERIMENT,
        SelectOutcome.ERROR,
        SelectErrorReason.MOTOR_TIMEOUT,
        minute=NOW,
    )

    base = f"qbrix:tenant:{TENANT}:health:select:{EXPERIMENT}:{NOW}:error"
    assert await store.client.get(base) == "1"
    assert await store.client.get(f"{base}:motor_timeout") == "1"
    assert 0 < await store.client.ttl(f"{base}:motor_timeout") <= SELECT_HEALTH_TTL_SEC


async def test_health_sums_the_minutes_in_the_window(store):
    for minute in (NOW - 9, NOW - 3, NOW):
        await store.record_select(TENANT, EXPERIMENT, SelectOutcome.OK, minute=minute)
    await store.record_select(TENANT, EXPERIMENT, SelectOutcome.CLIENT, minute=NOW - 1)
    await store.record_select(
        TENANT, EXPERIMENT, SelectOutcome.NOT_FOUND, minute=NOW - 2
    )
    for reason in (SelectErrorReason.STORE, SelectErrorReason.STORE):
        await store.record_select(
            TENANT, EXPERIMENT, SelectOutcome.ERROR, reason, minute=NOW - 5
        )
    await store.record_select(
        TENANT, EXPERIMENT, SelectOutcome.ERROR, SelectErrorReason.GATE, minute=NOW
    )

    health = await store.select_health(TENANT, EXPERIMENT, 10, now_minute=NOW)

    assert health == SelectHealth(
        ok=3, client=1, error=3, not_found=1, by_reason={"store": 2, "gate": 1}
    )


async def test_health_ignores_minutes_outside_the_window(store):
    await store.record_select(TENANT, EXPERIMENT, SelectOutcome.OK, minute=NOW - 10)
    await store.record_select(TENANT, EXPERIMENT, SelectOutcome.OK, minute=NOW + 1)

    health = await store.select_health(TENANT, EXPERIMENT, 10, now_minute=NOW)

    assert health == SelectHealth()


async def test_health_is_per_experiment_and_tenant(store):
    await store.record_select(TENANT, "other", SelectOutcome.OK, minute=NOW)
    await store.record_select("t2", EXPERIMENT, SelectOutcome.OK, minute=NOW)

    health = await store.select_health(TENANT, EXPERIMENT, 10, now_minute=NOW)

    assert health == SelectHealth()
