"""the learning record: params, applied count and the stream ack in one write."""

from __future__ import annotations

import asyncio

import fakeredis
import pytest
from redis.asyncio.client import Pipeline
from redis.exceptions import WatchError

from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent
from qbrixstore.redis.client import Learning
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.redis.streams import RedisStreamPublisher
from qbrixstore.stream import topology

pytestmark = pytest.mark.integration

TENANT = "t1"
EXPERIMENT = "exp"


def make_feedback() -> FeedbackEvent:
    return FeedbackEvent(
        tenant_id=TENANT,
        experiment_id=EXPERIMENT,
        request_id="req",
        arm_index=0,
        reward=1.0,
        context_id="ctx",
        context_vector=[],
        context_metadata={},
        timestamp_ms=1_000,
    )


@pytest.fixture
async def store(redis_server) -> RedisClient:
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
async def cortex(redis_server) -> RedisStreamConsumer:
    consumer = RedisStreamConsumer(topology.FEEDBACK, "cortex")
    await consumer.connect()
    await consumer.ensure_group()
    yield consumer
    await consumer.close()


async def deliver(n: int, consumer: RedisStreamConsumer) -> list[str]:
    publisher = RedisStreamPublisher(topology.FEEDBACK)
    await publisher.connect()
    for _ in range(n):
        await publisher.publish(make_feedback())
    await publisher.close()
    return [mid for mid, _ in await consumer.consume(batch_size=n, block_ms=0)]


def counting(ids: list[str]):
    """a train step whose params count the outcomes applied to them."""

    def train(experiment: dict | None, current: Learning) -> Learning | None:
        n = (current.params or {}).get("n", 0) + len(ids)
        return current.advance({"n": n}, ids)

    return train


async def pending(control, consumer: RedisStreamConsumer) -> int:
    return (await control.xpending(consumer.spec.name, consumer.group))["pending"]


class TestLearningRecord:
    def test_includes_compares_ids_numerically(self):
        learning = Learning(params=None, last_id="10-0")

        assert learning.includes("9-5")
        assert learning.includes("10-0")
        assert not learning.includes("10-1")
        assert not learning.includes("11-0")

    def test_advance_counts_and_keeps_the_highest_id(self):
        learning = Learning(params=None, applied=4, last_id="9-0")

        advanced = learning.advance({"n": 6}, ["10-0", "9-9"])

        assert advanced == Learning(params={"n": 6}, applied=6, last_id="10-0")

    def test_nothing_learned_reads_as_empty(self):
        assert Learning.decode(None, None) == Learning(params=None)


class TestApplyLearning:
    async def test_commits_params_record_and_ack_together(self, store, cortex, control):
        ids = await deliver(3, cortex)

        await store.apply_learning(
            TENANT, EXPERIMENT, counting(ids), lambda p: cortex.stage_ack(p, ids)
        )

        learning = await store.read_learning(TENANT, EXPERIMENT)
        assert learning == Learning(params={"n": 3}, applied=3, last_id=ids[-1])
        assert await pending(control, cortex) == 0
        assert await control.xlen(topology.FEEDBACK.name) == 0

    async def test_acks_without_writing_when_nothing_was_learned(
        self, store, cortex, control
    ):
        ids = await deliver(2, cortex)

        await store.apply_learning(
            TENANT, EXPERIMENT, lambda e, c: None, lambda p: cortex.stage_ack(p, ids)
        )

        assert await store.read_learning(TENANT, EXPERIMENT) == Learning(params=None)
        assert await pending(control, cortex) == 0

    async def test_a_failing_ack_leaves_everything_as_it_was(
        self, store, cortex, control
    ):
        ids = await deliver(3, cortex)

        def ack(pipe):
            raise ConnectionError("lost redis mid-write")

        with pytest.raises(ConnectionError):
            await store.apply_learning(TENANT, EXPERIMENT, counting(ids), ack)

        assert await store.read_learning(TENANT, EXPERIMENT) == Learning(params=None)
        assert await pending(control, cortex) == 3

    async def test_a_failing_exec_leaves_everything_as_it_was(
        self, store, cortex, control, monkeypatch
    ):
        ids = await deliver(3, cortex)

        async def broken(self, *args, **kwargs):
            raise ConnectionError("lost redis at exec")

        monkeypatch.setattr(Pipeline, "execute", broken)

        with pytest.raises(ConnectionError):
            await store.apply_learning(
                TENANT, EXPERIMENT, counting(ids), lambda p: cortex.stage_ack(p, ids)
            )
        monkeypatch.undo()

        assert await store.read_learning(TENANT, EXPERIMENT) == Learning(params=None)
        assert await pending(control, cortex) == 3

    async def test_a_reset_during_training_reruns_it_on_the_fresh_state(
        self, store, cortex, control, redis_server
    ):
        """the reset must not be overwritten by a write trained before it."""
        await store.apply_learning(
            TENANT, EXPERIMENT, counting(["1-0"]), lambda pipe: None
        )
        ids = await deliver(1, cortex)
        other = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
        seen: list[Learning] = []
        train = counting(ids)

        def racing(experiment, current):
            seen.append(current)
            if len(seen) == 1:
                other.delete(
                    store._param_key(TENANT, EXPERIMENT),
                    store._learning_key(TENANT, EXPERIMENT),
                )
            return train(experiment, current)

        await store.apply_learning(
            TENANT, EXPERIMENT, racing, lambda p: cortex.stage_ack(p, ids)
        )

        assert [s.applied for s in seen] == [1, 0]
        learning = await store.read_learning(TENANT, EXPERIMENT)
        assert learning == Learning(params={"n": 1}, applied=1, last_id=ids[0])
        assert await pending(control, cortex) == 0

    async def test_gives_up_when_the_state_never_settles(self, store, redis_server):
        other = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
        attempts = 0

        def always_raced(experiment, current):
            nonlocal attempts
            attempts += 1
            other.set(store._experiment_key(TENANT, EXPERIMENT), "{}")
            return None

        with pytest.raises(WatchError):
            await store.apply_learning(
                TENANT, EXPERIMENT, always_raced, lambda pipe: None
            )

        assert attempts == 5

    async def test_hands_train_the_experiment_record(self, store):
        await store.set_experiment(TENANT, EXPERIMENT, {"policy": "beta_ts"})
        seen = []

        await store.apply_learning(
            TENANT,
            EXPERIMENT,
            lambda experiment, current: seen.append(experiment),
            lambda pipe: None,
        )

        assert seen == [{"policy": "beta_ts"}]


class TestReadLearning:
    async def test_never_pairs_params_with_another_writes_record(self, store):
        async def write(i: int) -> None:
            ids = [f"{i}-0"]
            await store.apply_learning(
                TENANT, EXPERIMENT, counting(ids), lambda pipe: None
            )

        async def read() -> list[Learning]:
            reads = []
            for _ in range(50):
                reads.append(await store.read_learning(TENANT, EXPERIMENT))
                await asyncio.sleep(0)
            return reads

        writes = asyncio.gather(*(write(i) for i in range(1, 51)))
        reads, _ = await asyncio.gather(read(), writes)

        for learning in reads:
            assert (learning.params or {}).get("n", 0) == learning.applied

        final = await store.read_learning(TENANT, EXPERIMENT)
        assert final.applied == 50
        assert final.params == {"n": 50}


class TestResetAndDelete:
    async def seed(self, store):
        await store.set_experiment(TENANT, EXPERIMENT, {"policy": "beta_ts"})
        await store.apply_learning(
            TENANT, EXPERIMENT, counting(["1-0"]), lambda pipe: None
        )
        assert (await store.read_learning(TENANT, EXPERIMENT)).applied == 1

    async def test_reset_clears_params_and_record(self, store):
        await self.seed(store)

        await store.reset_learning(TENANT, EXPERIMENT)

        assert await store.read_learning(TENANT, EXPERIMENT) == Learning(params=None)
        assert await store.get_experiment(TENANT, EXPERIMENT) is not None

    async def test_delete_experiment_clears_the_record_too(self, store, control):
        await self.seed(store)

        await store.delete_experiment(TENANT, EXPERIMENT)

        assert await store.read_learning(TENANT, EXPERIMENT) == Learning(params=None)
        assert not await control.exists(store._learning_key(TENANT, EXPERIMENT))


class TestStageAck:
    async def test_ack_keeps_entries_on_a_fanned_out_stream(
        self, redis_server, control
    ):
        trace = RedisStreamConsumer(topology.SELECTION, "trace")
        await trace.connect()
        await trace.ensure_group()
        publisher = RedisStreamPublisher(topology.SELECTION)
        await publisher.connect()
        await publisher.publish(
            SelectionEvent(
                tenant_id=TENANT,
                experiment_id=EXPERIMENT,
                request_id="req",
                event_id="evt",
                arm_id="arm",
                arm_name="arm",
                arm_index=0,
                is_default=False,
                context_id="ctx",
                context_vector=[],
                context_metadata={},
                timestamp_ms=1_000,
                policy="beta_ts",
            )
        )
        ids = [mid for mid, _ in await trace.consume(batch_size=1, block_ms=0)]

        await trace.ack(ids)

        assert await pending(control, trace) == 0
        assert await control.xlen(topology.SELECTION.name) == 1
        await publisher.close()
        await trace.close()
