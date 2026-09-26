from __future__ import annotations

import fakeredis.aioredis
import pytest

from qbrixstore.config import RedisSettings
from qbrixstore.event import AuditEvent
from qbrixstore.event import SelectionEvent
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.stream import topology

pytestmark = pytest.mark.integration


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


def make_audit() -> AuditEvent:
    return AuditEvent(
        name="experiment.created",
        tenant_id="t1",
        actor_id="",
        resource_type="experiment",
        resource_id="exp",
        payload={},
        timestamp_ms=1_000,
    )


async def _consumer(fake, spec, group: str) -> RedisStreamConsumer:
    c = RedisStreamConsumer(spec, group, settings=RedisSettings(), consumer_name="w0")
    c._client = fake
    await fake.xgroup_create(spec.name, group, id="0", mkstream=True)
    return c


async def test_fanned_out_stream_keeps_entry_for_other_group():
    stream = topology.SELECTION.name
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await fake.xadd(stream, make_event("t1").to_dict())

    metering = await _consumer(fake, topology.SELECTION, "metering")
    await _consumer(fake, topology.SELECTION, "trace")  # second group, same stream

    msgs = await metering.consume(batch_size=10, block_ms=10)
    await metering.ack([mid for mid, _ in msgs])

    # entry survives -> the trace group can still read it
    assert await fake.xlen(stream) == 1
    res = await fake.xreadgroup("trace", "w0", {stream: ">"}, count=10)
    assert res and res[0][1], "trace group must still see the entry metering acked"


async def test_single_group_stream_removes_entry_on_ack():
    stream = topology.AUDIT.name
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await fake.xadd(stream, make_audit().to_dict())

    consumer = await _consumer(fake, topology.AUDIT, "trace")
    msgs = await consumer.consume(batch_size=10, block_ms=10)
    await consumer.ack([mid for mid, _ in msgs])

    assert await fake.xlen(stream) == 0
