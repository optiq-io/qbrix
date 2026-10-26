"""what redis holds for the sealer: each cycle's mark in its learning record,
the sealer's own mark, the ledger's progress, and where the trace group has
got to on a stream."""

from __future__ import annotations

import json

import pytest

from qbrixstore.redis.client import LEDGER_PROGRESS_KEY
from qbrixstore.redis.client import Learning
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.health import LEDGER_PROGRESS_TTL_SEC
from qbrixstore.redis.health import LedgerProgress
from qbrixstore.redis.health import OutcomeDisposition
from qbrixstore.redis.streams import oldest_unfinished
from qbrixstore.redis.streams import stream_ms
from qbrixstore.stream import topology

pytestmark = pytest.mark.integration

SPEC = topology.EVENT


@pytest.fixture
async def store(redis_server) -> RedisClient:
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


class TestLearningRecord:
    def test_the_mark_round_trips(self):
        learning = Learning(params={"a": 1}, applied=3, sealed_up_to=1_700)

        decoded = Learning.decode(json.dumps(learning.params), learning.encode_record())

        assert decoded == learning

    def test_a_record_written_before_the_mark_reads_as_zero(self):
        record = json.dumps({"applied": 4, "last_id": "4-0"})

        assert Learning.decode(None, record).sealed_up_to == 0

    def test_seal_adds_the_decisions_and_moves_the_mark(self):
        current = Learning(params=None, applied=2, last_id="9-0", sealed_up_to=100)

        sealed = current.seal({"a": 2}, 3, 200)

        assert sealed == Learning(
            params={"a": 2}, applied=5, last_id="9-0", sealed_up_to=200
        )

    def test_advance_keeps_the_mark(self):
        current = Learning(params=None, sealed_up_to=100)

        assert current.advance({}, ["5-0"]).sealed_up_to == 100


class TestSealerKeys:
    async def test_the_mark_is_absent_until_set(self, store):
        assert await store.sealer_mark() is None

        await store.set_sealer_mark(1_234)

        assert await store.sealer_mark() == 1_234
        assert await store.client.ttl("qbrix:sealer:sealed_up_to") == -1

    async def test_progress_expires_so_a_stopped_cortex_shows_as_absent(self, store):
        progress = LedgerProgress(complete_up_to_ms=10, lag_ms=5, checked_ms=15)

        await store.set_ledger_progress(progress)

        assert await store.ledger_progress() == progress
        assert (
            0 < await store.client.ttl(LEDGER_PROGRESS_KEY) <= LEDGER_PROGRESS_TTL_SEC
        )

    async def test_server_time_is_redis_clock_in_ms(self, store):
        seconds, _ = await store.client.time()

        assert abs(await store.server_time_ms() - seconds * 1000) < 2_000


class TestOldestUnfinished:
    async def test_no_stream_is_nothing_unfinished(self, store):
        assert await oldest_unfinished(store.client, SPEC, "trace") is None

    async def test_a_group_that_read_and_acked_everything_has_finished(
        self, store, control
    ):
        await control.xgroup_create(SPEC.name, "trace", id="0", mkstream=True)
        await control.xadd(SPEC.name, {"x": "1"}, id="100-0")
        await control.xreadgroup("trace", "c", {SPEC.name: ">"})
        await control.xack(SPEC.name, "trace", "100-0")

        assert await oldest_unfinished(store.client, SPEC, "trace") is None

    async def test_an_undelivered_entry_is_unfinished(self, store, control):
        await control.xgroup_create(SPEC.name, "trace", id="0", mkstream=True)
        await control.xadd(SPEC.name, {"x": "1"}, id="100-0")
        await control.xreadgroup("trace", "c", {SPEC.name: ">"}, count=1)
        await control.xack(SPEC.name, "trace", "100-0")
        await control.xadd(SPEC.name, {"x": "2"}, id="200-0")

        assert await oldest_unfinished(store.client, SPEC, "trace") == "200-0"

    async def test_a_pending_entry_is_older_than_an_undelivered_one(
        self, store, control
    ):
        await control.xgroup_create(SPEC.name, "trace", id="0", mkstream=True)
        await control.xadd(SPEC.name, {"x": "1"}, id="100-0")
        await control.xreadgroup("trace", "c", {SPEC.name: ">"})
        await control.xadd(SPEC.name, {"x": "2"}, id="200-0")

        assert await oldest_unfinished(store.client, SPEC, "trace") == "100-0"

    async def test_a_missing_group_has_finished_nothing(self, store, control):
        await control.xadd(SPEC.name, {"x": "1"}, id="100-5")

        assert await oldest_unfinished(store.client, SPEC, "trace") == "100-5"

    async def test_another_groups_progress_does_not_count(self, store, control):
        spec = topology.SELECTION
        await control.xgroup_create(spec.name, "trace", id="0", mkstream=True)
        await control.xgroup_create(spec.name, "metering", id="0")
        await control.xadd(spec.name, {"x": "1"}, id="100-0")
        await control.xreadgroup("metering", "m", {spec.name: ">"})
        await control.xack(spec.name, "metering", "100-0")

        assert await oldest_unfinished(store.client, spec, "trace") == "100-0"


def test_stream_ms_is_the_entry_time():
    assert stream_ms("1700000000123-7") == 1700000000123


async def test_the_sealers_reasons_are_reported_with_the_others(store):
    await store.count_outcomes(
        "t1",
        "cyc",
        {
            OutcomeDisposition.LATE: 2,
            OutcomeDisposition.DUPLICATE: 1,
            OutcomeDisposition.LEARNED: 4,
        },
    )

    health = await store.outcome_health("t1", "cyc", window_minutes=5)

    assert health.learned == 4
    assert health.by_reason["late"] == 2
    assert health.by_reason["duplicate"] == 1
    assert health.not_learned == 3
