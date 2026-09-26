"""shared fixtures for qbrixstore tests."""

from __future__ import annotations

import asyncio

import fakeredis
import pytest
from fakeredis.aioredis import FakeRedis

import qbrixstore.redis.pubsub as _pubsub_module
import qbrixstore.redis.streams as _streams_module


class BlockingFakeRedis(FakeRedis):
    """fakeredis returns from xreadgroup without ever suspending.

    a real blocking read yields to the event loop; this one does not, so a
    consumer loop built on it never gives another task a turn and the loop
    starves. honouring `block` restores the suspension point the loop relies on.
    """

    async def xreadgroup(self, *args, block: int | None = None, **kwargs):
        result = await super().xreadgroup(*args, block=block, **kwargs)
        await asyncio.sleep(0.001 if not result else 0)
        return result


@pytest.fixture
def redis_server(monkeypatch) -> fakeredis.FakeServer:
    """one shared fake redis; every connect() opens a distinct client on it.

    publishers, consumers and subscribers hold separate connections in
    production, so two components here are as separate as two pods are.
    """
    server = fakeredis.FakeServer()

    def _from_url(*_args, **_kwargs):
        return BlockingFakeRedis(server=server, decode_responses=True)

    monkeypatch.setattr(_streams_module.redis, "from_url", _from_url)
    monkeypatch.setattr(_pubsub_module.redis, "from_url", _from_url)
    return server


@pytest.fixture
def control(redis_server) -> FakeRedis:
    """a client for the test itself to publish with and assert against."""
    return FakeRedis(server=redis_server, decode_responses=True)
