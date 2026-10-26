"""a launched loop's cycle runs on the learning path unchanged.

invariants verified:
  the record the proxy writes when a loop is launched is served by motor and
  trained by cortex under the cycle's id: motor chooses one of the loop's
  options, an outcome for that choice is learned, and the next motor reads
  what was learned. select(loop) answers through the same motor.
"""

from __future__ import annotations

import fakeredis
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from cortexsvc.trainer import BatchTrainer
from motorsvc.config import MotorSettings
from motorsvc.service import MotorService
from qbrixstore.event import FeedbackEvent
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.redis.streams import RedisStreamPublisher
from qbrixstore.stream import topology

from proxysvc.core.actor import Actor

TENANT = "dev-tenant"
ACTOR = Actor.member("user-ada")


@pytest_asyncio.fixture
async def fake_redis_client(monkeypatch):
    """one redis server shared by the proxy, motor and cortex."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda *_a, **_k: FakeRedis(server=server, decode_responses=True),
    )
    client = FakeRedis(server=server, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def cycle(wired_app) -> dict:
    svc = wired_app.svc
    await svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        actor=ACTOR,
    )
    draft = (
        await svc.create_loop(
            TENANT,
            name="Checkout headline",
            metric="purchase",
            options=[{"name": "Control"}, {"name": "Urgency"}, {"name": "Social"}],
            actor=ACTOR,
        )
    ).value
    loop = (await svc.launch_loop(TENANT, draft["key"], actor=ACTOR)).value
    return {"id": loop["cycle"]["id"], "key": loop["key"], "options": loop["options"]}


async def _motor() -> MotorService:
    motor = MotorService(MotorSettings())
    await motor.start()
    return motor


async def _outcome(cycle_id: str, arm_index: int, reward: float):
    publisher = RedisStreamPublisher(topology.FEEDBACK)
    await publisher.connect()
    await publisher.publish(
        FeedbackEvent(
            tenant_id=TENANT,
            experiment_id=cycle_id,
            request_id="req-1",
            arm_index=arm_index,
            reward=reward,
            context_id="unit-1",
            context_vector=[],
            context_metadata={},
            timestamp_ms=1234567890,
        )
    )
    await publisher.close()


async def test_motor_serves_and_cortex_trains_the_cycle(cycle):
    motor = await _motor()
    choice = await motor.select(TENANT, cycle["id"], "unit-1", [], {})
    await motor.stop()

    option = cycle["options"][choice["arm"]["index"]]
    assert choice["arm"] == {
        "id": option["id"],
        "name": option["key"],
        "index": choice["arm"]["index"],
    }
    assert choice["policy"] == "BetaTSPolicy"

    store = RedisClient()
    await store.connect()
    consumer = RedisStreamConsumer(topology.FEEDBACK, "cortex")
    await consumer.connect()
    await consumer.ensure_group()
    await _outcome(cycle["id"], choice["arm"]["index"], 1.0)
    entries = await consumer.consume(batch_size=1, block_ms=0)
    messages = [(mid, FeedbackEvent.from_dict(data)) for mid, data in entries]

    await BatchTrainer(store, consumer).train_experiment(TENANT, cycle["id"], messages)

    learning = await store.read_learning(TENANT, cycle["id"])
    expected = [1.0, 1.0, 1.0]
    expected[choice["arm"]["index"]] = 2.0
    assert learning.applied == 1
    assert learning.params["alpha"] == expected

    fresh = await _motor()
    await fresh.select(TENANT, cycle["id"], "unit-2", [], {})
    served = fresh._param_backend.get(TENANT, cycle["id"])
    await fresh.stop()
    await consumer.close()
    await store.close()

    assert list(served.alpha) == expected


async def test_select_answers_from_motor_and_records_the_decision(wired_app, cycle):
    motor = await _motor()
    wired_app.svc._loop_select_service._motor_client = motor

    answer = await wired_app.svc.select_loop(TENANT, cycle["key"], "unit-1")
    await wired_app.events.drain()
    await motor.stop()

    (event,) = wired_app.selection_spy.events
    option = cycle["options"][event.arm_index]
    assert answer["reason"] == "live"
    assert answer["option"]["key"] == option["key"]
    assert answer["request_id"] == event.request_id
    assert event.experiment_id == cycle["id"]
    assert event.policy == "BetaTSPolicy"
