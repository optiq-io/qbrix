"""unit tests for proxy's tenant binding of the broadcast bus.

BroadcastBus itself lives in qbrixstore and is tested there
(lib/store/tests/test_pubsub.py) — cross-replica delivery, failure isolation and
the reconnect loop. what stays here is what is proxy's: that the binding uses the
one shared channel, and that the no-redis stand-in still evicts locally.
"""

from __future__ import annotations

import asyncio

import fakeredis
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

import qbrixstore.redis.pubsub as _pubsub_module
from qbrixstore.channel import TENANT_INVALIDATION_CHANNEL
from qbrixstore.config import RedisSettings
from qbrixstore.redis.pubsub import BroadcastBus

from proxysvc.core.invalidation import LocalTenantInvalidation
from proxysvc.core.invalidation import TenantInvalidation


@pytest_asyncio.fixture
def redis_server(monkeypatch):
    """one shared fake redis; every connect() opens a distinct client on it."""
    server = fakeredis.FakeServer()
    clients: list[FakeRedis] = []

    def _from_url(*_args, **_kwargs):
        client = FakeRedis(server=server, decode_responses=True)
        clients.append(client)
        return client

    monkeypatch.setattr(_pubsub_module.redis, "from_url", _from_url)
    return server


def _new_bus(channel: str = TENANT_INVALIDATION_CHANNEL) -> BroadcastBus:
    return BroadcastBus(channel, RedisSettings())


async def _bus(*callbacks, channel: str = TENANT_INVALIDATION_CHANNEL) -> BroadcastBus:
    """a started bus with its callbacks already registered.

    registration happens before start(), matching ProxyRuntime — and so that
    subscription-confirmation frames, which arrive at subscribe time, are
    observed by the callbacks if the consumer ever fails to filter them.
    """
    bus = _new_bus(channel)
    for callback in callbacks:
        bus.register(callback)
    await bus.start()
    # let the listener finish subscribing before anything is published;
    # pubsub drops messages sent to a channel with no subscriber yet
    await asyncio.sleep(0.05)
    return bus


async def _wait_for(received: list, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not received and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.01)


class TestChannel:
    def test_channel_is_shared_and_stable(self):
        """metersvc subscribes to this exact name; renaming it here
        without renaming it there is a silent failure."""
        assert TENANT_INVALIDATION_CHANNEL == "qbrix:invalidate:tenant"

    def test_tenant_binding_uses_the_shared_channel(self):
        """the binding exists to remove the chance of a caller passing the
        wrong channel; that is only true if it hard-binds this one."""
        assert TenantInvalidation()._channel == TENANT_INVALIDATION_CHANNEL

    async def test_buses_on_different_channels_do_not_cross_talk(self, redis_server):
        received: list[str] = []
        publisher = await _bus()
        other = await _bus(received.append, channel="qbrix:invalidate:other")

        try:
            await publisher.publish("tenant-a")
            await asyncio.sleep(0.2)
        finally:
            await publisher.stop()
            await other.stop()

        assert received == []


class TestLocalTenantInvalidation:
    """the no-redis stand-in: still evicts, just tells nobody."""

    async def test_publish_dispatches_to_registered_callbacks(self):
        received: list[str] = []
        local = LocalTenantInvalidation()
        local.register(received.append)

        await local.publish("tenant-a")

        assert received == ["tenant-a"]

    async def test_start_and_stop_are_inert(self):
        local = LocalTenantInvalidation()
        await local.start()
        await local.stop()


@pytest.mark.parametrize("tenant_id", ["tenant-a", "tenant-b"])
async def test_dispatch_carries_the_tenant_id(redis_server, tenant_id):
    bus = TenantInvalidation(RedisSettings())
    received: list[str] = []
    bus.register(received.append)

    await bus.publish(tenant_id)

    assert received == [tenant_id]
