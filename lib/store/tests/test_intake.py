"""what a cycle received at the proxy, and the batched outcome reader."""

from __future__ import annotations

import pytest

from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import INTAKE_TTL_PAST_WINDOW_SEC
from qbrixstore.redis.health import Intake
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.health import OutcomeHealth
from qbrixstore.redis.health import SelectErrorReason
from qbrixstore.redis.health import SelectOutcome

pytestmark = pytest.mark.integration

TENANT = "t1"
CYCLE = "cyc"
WINDOW_MS = 7 * 24 * 60 * 60 * 1000
NOW = 29_000_000


@pytest.fixture
async def store(redis_server) -> RedisClient:
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


async def _intake(store: RedisClient) -> Intake:
    return (await store.intakes([(TENANT, CYCLE)]))[(TENANT, CYCLE)]


async def test_an_answered_call_with_a_window_is_a_decision(store):
    for _ in range(3):
        await store.record_select(TENANT, CYCLE, SelectOutcome.OK, window_ms=WINDOW_MS)

    assert await _intake(store) == Intake(decisions=3, since_outcome=3)
    key = f"qbrix:tenant:{TENANT}:health:intake:{CYCLE}"
    ttl_ms = await store.client.pttl(key)
    assert WINDOW_MS < ttl_ms <= WINDOW_MS + INTAKE_TTL_PAST_WINDOW_SEC * 1000


async def test_failed_calls_and_calls_without_a_window_are_no_decision(store):
    await store.record_select(
        TENANT,
        CYCLE,
        SelectOutcome.ERROR,
        SelectErrorReason.MOTOR_TIMEOUT,
        window_ms=WINDOW_MS,
    )
    await store.record_select(TENANT, CYCLE, SelectOutcome.OK)

    assert await _intake(store) == Intake()


async def test_an_outcome_restarts_the_count_since_the_last_one(store):
    for _ in range(5):
        await store.record_select(TENANT, CYCLE, SelectOutcome.OK, window_ms=WINDOW_MS)
    await store.record_intake(TENANT, CYCLE, WINDOW_MS, at_ms=1_000)
    await store.record_select(TENANT, CYCLE, SelectOutcome.OK, window_ms=WINDOW_MS)

    assert await _intake(store) == Intake(
        decisions=6, outcomes=1, since_outcome=1, last_outcome_ms=1_000
    )


async def test_a_cycle_that_received_nothing_reads_empty(store):
    assert await store.intakes([]) == {}
    assert await _intake(store) == Intake()


async def test_outcomes_health_reads_many_cycles_and_only_the_asked_dispositions(
    store,
):
    await store.count_outcomes(
        TENANT,
        "a",
        {
            OutcomeDisposition.LEARNED: 7,
            OutcomeDisposition.LATE: 2,
            OutcomeDisposition.TRAIN_ERROR: 4,
        },
        minute=NOW - 59,
    )
    await store.count_outcomes(
        TENANT, "a", {OutcomeDisposition.LEARNED: 1}, minute=NOW - 60
    )
    await store.count_outcomes(TENANT, "b", {OutcomeDisposition.INVALID: 3}, minute=NOW)

    found = await store.outcomes_health(
        [(TENANT, "a"), (TENANT, "b"), (TENANT, "c")],
        60,
        [
            OutcomeDisposition.LEARNED,
            OutcomeDisposition.LATE,
            OutcomeDisposition.INVALID,
        ],
        now_minute=NOW,
    )

    assert found == {
        (TENANT, "a"): OutcomeHealth(learned=7, not_learned=2, by_reason={"late": 2}),
        (TENANT, "b"): OutcomeHealth(not_learned=3, by_reason={"invalid": 3}),
        (TENANT, "c"): OutcomeHealth(),
    }
