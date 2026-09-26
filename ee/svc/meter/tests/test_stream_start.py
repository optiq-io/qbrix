from __future__ import annotations

import fakeredis.aioredis
import pytest

from qbrixstore.config import RedisSettings
from qbrixstore.event import SelectionEvent
from qbrixstore.redis import streams
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.stream import topology

pytestmark = pytest.mark.integration

STREAM = topology.SELECTION.name


def make_event(tenant_id: str) -> SelectionEvent:
    return SelectionEvent(
        tenant_id=tenant_id,
        experiment_id="exp",
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


async def _connected_consumer(fake, monkeypatch, group: str) -> RedisStreamConsumer:
    monkeypatch.setattr(streams.redis, "from_url", lambda *a, **kw: fake)
    consumer = RedisStreamConsumer(
        topology.SELECTION,
        group,
        settings=RedisSettings(),
        consumer_name="w0",
    )
    await consumer.connect()
    return consumer


async def test_fresh_group_at_tail_skips_backlog(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await fake.xadd(STREAM, make_event("t1").to_dict())
    await fake.xadd(STREAM, make_event("t2").to_dict())

    # start position comes from the registry, not from this call site
    consumer = await _connected_consumer(fake, monkeypatch, "metering")

    # pre-existing backlog is not delivered to the fresh group
    msgs = await consumer.consume(batch_size=10, block_ms=10)
    assert msgs == []

    # entries added after group creation are delivered
    await fake.xadd(STREAM, make_event("t3").to_dict())
    msgs = await consumer.consume(batch_size=10, block_ms=10)
    assert len(msgs) == 1
    assert msgs[0][1]["tenant_id"] == "t3"


async def test_default_group_drains_full_history(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await fake.xadd(STREAM, make_event("t1").to_dict())
    await fake.xadd(STREAM, make_event("t2").to_dict())

    # cortex/trace regression guard: default start still drains from 0
    consumer = await _connected_consumer(fake, monkeypatch, "trace")

    msgs = await consumer.consume(batch_size=10, block_ms=10)
    assert [e["tenant_id"] for _, e in msgs] == ["t1", "t2"]
