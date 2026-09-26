"""unit tests for BroadcastBus.

migrated here from svc/proxy/tests/unit/core/test_invalidation.py, which held
them only because lib/store had no suite with a fake redis in it. the bus is
generic — proxy binds it to a tenant channel, metersvc is the next subscriber —
so the tests that exercise the bus itself belong with the bus. the tenant
binding's own tests stay in proxy.

each bus connects through its own fake client against a shared fake server, so
publisher and subscriber are as separate here as two pods are in a cluster.
"""

from __future__ import annotations

import asyncio

import pytest

from qbrixstore.config import RedisSettings
from qbrixstore.redis.pubsub import BroadcastBus

pytestmark = pytest.mark.integration

CHANNEL = "qbrix:test:broadcast"


def new_bus(channel: str = CHANNEL) -> BroadcastBus:
    return BroadcastBus(channel, RedisSettings())


async def started_bus(*callbacks, channel: str = CHANNEL) -> BroadcastBus:
    """a started bus with its callbacks already registered.

    registration happens before start(), matching how the composition roots do
    it — and so that subscription-confirmation frames, which arrive at subscribe
    time, are observed by the callbacks if the consumer ever fails to filter them.
    """
    bus = new_bus(channel)
    for callback in callbacks:
        bus.register(callback)
    await bus.start()
    # let the listener finish subscribing before anything is published;
    # pubsub drops messages sent to a channel with no subscriber yet
    await asyncio.sleep(0.05)
    return bus


async def wait_for(received: list, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not received and loop.time() < deadline:
        await asyncio.sleep(0.01)


class TestCrossReplica:
    async def test_publish_reaches_a_second_bus(self, redis_server):
        """the whole reason this component exists.

        publisher and subscriber are separate instances on separate connections,
        exactly as two replicas are separate processes.
        """
        received: list[str] = []
        publisher = await started_bus()
        subscriber = await started_bus(received.append)

        try:
            await publisher.publish("payload-a")
            await wait_for(received)
        finally:
            await publisher.stop()
            await subscriber.stop()

        # exactly one entry: subscription-confirmation frames must not surface
        assert received == ["payload-a"]

    async def test_every_subscriber_receives_the_message(self, redis_server):
        """fan-out, not work distribution — the property that ruled out the
        consumer-group streams used elsewhere in this codebase."""
        publisher = await started_bus()
        received: list[list[str]] = [[], [], []]
        subscribers = [await started_bus(inbox.append) for inbox in received]

        try:
            await publisher.publish("payload-a")
            for inbox in received:
                await wait_for(inbox)
        finally:
            await publisher.stop()
            for subscriber in subscribers:
                await subscriber.stop()

        assert received == [["payload-a"], ["payload-a"], ["payload-a"]]

    async def test_publisher_dispatches_locally_without_waiting_for_redis(
        self, redis_server
    ):
        """the replica serving the change must act on it itself, even before the
        broadcast completes."""
        bus = new_bus()
        received: list[str] = []
        bus.register(received.append)

        # never started, so nothing is connected — only the local dispatch runs
        await bus.publish("payload-a")

        assert received == ["payload-a"]

    async def test_buses_on_different_channels_do_not_cross_talk(self, redis_server):
        received: list[str] = []
        publisher = await started_bus()
        other = await started_bus(received.append, channel="qbrix:test:other")

        try:
            await publisher.publish("payload-a")
            await asyncio.sleep(0.2)
        finally:
            await publisher.stop()
            await other.stop()

        assert received == []


class TestFailureIsolation:
    async def test_redis_failure_does_not_propagate(self, redis_server, monkeypatch):
        """a redis blip must not fail the request that triggered the broadcast."""
        received: list[str] = []
        bus = await started_bus(received.append)

        async def _boom(_message):
            raise ConnectionError("redis down")

        monkeypatch.setattr(bus._publisher, "publish", _boom)

        try:
            await bus.publish("payload-a")
        finally:
            await bus.stop()

        assert received == ["payload-a"]

    async def test_raising_callback_does_not_block_the_others(self, redis_server):
        bus = new_bus()
        received: list[str] = []

        def _boom(_message):
            raise RuntimeError("subscriber is broken")

        bus.register(_boom)
        bus.register(received.append)

        await bus.publish("payload-a")

        assert received == ["payload-a"]


class TestLifecycle:
    async def test_stop_cancels_the_listener(self, redis_server):
        bus = await started_bus()
        task = bus._task

        await bus.stop()

        assert task.done()
        assert bus._task is None

    async def test_listener_resubscribes_after_a_dropped_connection(
        self, redis_server, monkeypatch
    ):
        """a disconnect must be a reconnect, not a dead replica: without the retry
        loop the bus goes silent for the lifetime of the process."""
        bus = new_bus()
        received: list[str] = []
        bus.register(received.append)

        calls = {"n": 0}
        real_connect = bus._consumer.connect

        async def _fail_once():
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("subscription dropped")
            await real_connect()

        monkeypatch.setattr(bus._consumer, "connect", _fail_once)
        await bus.start()

        publisher = await started_bus()
        try:
            # first attempt fails; the loop backs off then resubscribes
            await asyncio.sleep(0.8)
            await publisher.publish("payload-a")
            await wait_for(received)
        finally:
            await bus.stop()
            await publisher.stop()

        assert calls["n"] >= 2
        assert received == ["payload-a"]
