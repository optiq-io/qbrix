"""per-minute outcome disposition counters and the windowed reader."""

from __future__ import annotations

import pytest

from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import OUTCOME_HEALTH_TTL_SEC
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.health import OutcomeHealth

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


async def test_count_writes_the_disposition_key_with_a_ttl(store):
    await store.count_outcomes(
        TENANT, EXPERIMENT, {OutcomeDisposition.PAUSED: 3}, minute=NOW
    )

    key = f"qbrix:tenant:{TENANT}:health:outcome:{EXPERIMENT}:{NOW}:paused"
    assert await store.client.get(key) == "3"
    assert 0 < await store.client.ttl(key) <= OUTCOME_HEALTH_TTL_SEC


async def test_a_zero_count_writes_nothing(store):
    await store.count_outcomes(
        TENANT, EXPERIMENT, {OutcomeDisposition.LEARNED: 0}, minute=NOW
    )

    assert await store.client.keys("*") == []


async def test_health_sums_the_window_and_splits_learned_from_reasons(store):
    for minute, counts in [
        (NOW - 59, {OutcomeDisposition.LEARNED: 10}),
        (NOW - 30, {OutcomeDisposition.LEARNED: 5, OutcomeDisposition.PAUSED: 2}),
        (NOW, {OutcomeDisposition.TRAIN_ERROR: 1}),
        (NOW, {OutcomeDisposition.REJECTED_TOKEN_EXPIRED: 4}),
        (NOW - 60, {OutcomeDisposition.LEARNED: 100}),
    ]:
        await store.count_outcomes(TENANT, EXPERIMENT, counts, minute=minute)

    health = await store.outcome_health(TENANT, EXPERIMENT, 60, now_minute=NOW)

    assert health == OutcomeHealth(
        learned=15,
        not_learned=7,
        by_reason={"paused": 2, "train_error": 1, "rejected_token_expired": 4},
        last_arrival_ms=None,
    )


async def test_health_is_scoped_to_its_experiment_and_tenant(store):
    await store.count_outcomes(
        TENANT, "other", {OutcomeDisposition.LEARNED: 1}, minute=NOW
    )
    await store.count_outcomes(
        "t2", EXPERIMENT, {OutcomeDisposition.LEARNED: 1}, minute=NOW
    )

    assert (
        await store.outcome_health(TENANT, EXPERIMENT, 60, now_minute=NOW)
        == OutcomeHealth()
    )


async def test_staged_counts_land_with_the_callers_transaction(store):
    async with store.client.pipeline(transaction=True) as pipe:
        store.stage_outcomes(
            pipe,
            TENANT,
            EXPERIMENT,
            {OutcomeDisposition.LEARNED: 2},
            last_arrival_ms=1_700_000_000_000,
            minute=NOW,
        )
        await pipe.execute()

    health = await store.outcome_health(TENANT, EXPERIMENT, 1, now_minute=NOW)
    assert health.learned == 2
    assert health.last_arrival_ms == 1_700_000_000_000
    key = f"qbrix:tenant:{TENANT}:health:outcome:{EXPERIMENT}:last_arrival"
    assert 0 < await store.client.ttl(key) <= OUTCOME_HEALTH_TTL_SEC


async def test_staged_counts_are_dropped_with_a_discarded_transaction(store):
    async with store.client.pipeline(transaction=True) as pipe:
        pipe.multi()
        store.stage_outcomes(
            pipe,
            TENANT,
            EXPERIMENT,
            {OutcomeDisposition.LEARNED: 2},
            last_arrival_ms=1,
            minute=NOW,
        )
        await pipe.reset()

    assert (
        await store.outcome_health(TENANT, EXPERIMENT, 1, now_minute=NOW)
        == OutcomeHealth()
    )


async def test_invalid_outcomes_are_counted_per_tenant(store):
    await store.count_invalid_outcome(TENANT, minute=NOW - 1)
    await store.count_invalid_outcome(TENANT, minute=NOW)
    await store.count_invalid_outcome("t2", minute=NOW)
    await store.count_invalid_outcome(TENANT, minute=NOW - 10)

    assert await store.invalid_outcomes(TENANT, 5, now_minute=NOW) == 2
    key = f"qbrix:tenant:{TENANT}:health:outcome_invalid:{NOW}"
    assert 0 < await store.client.ttl(key) <= OUTCOME_HEALTH_TTL_SEC
    assert (
        await store.outcome_health(TENANT, EXPERIMENT, 60, now_minute=NOW)
        == OutcomeHealth()
    )
