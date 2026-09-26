"""shared fixtures for tracesvc tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# make sibling modules (e.g. trace_factories) importable without __init__.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fakeredis
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from unittest.mock import Mock
from fakeredis.aioredis import FakeRedis

import qbrixstore.redis.streams as _streams_module

from tracesvc import server as server_module
from tracesvc.config import TraceSettings
from tracesvc.service import TraceService

from trace_factories import FakeClickHouse


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
def redis_server(monkeypatch):
    """one shared fake redis; every connect() opens a distinct client on it.

    consumers hold separate connections in production, so they do here too.
    """
    server = fakeredis.FakeServer()

    def _from_url(*_args, **_kwargs):
        return BlockingFakeRedis(server=server, decode_responses=True)

    monkeypatch.setattr(_streams_module.redis, "from_url", _from_url)
    return server


@pytest.fixture
def control(redis_server) -> FakeRedis:
    """a client for the test itself to publish with and assert against."""
    return FakeRedis(server=redis_server, decode_responses=True)


@pytest.fixture
def clickhouse() -> FakeClickHouse:
    return FakeClickHouse()


@pytest_asyncio.fixture
async def make_service(redis_server, clickhouse, monkeypatch):
    """start a trace service with clickhouse faked out.

    only the clickhouse client and its table migrations are stubbed; the three
    workers, their consumers and the stats are wired by the real start().
    """
    monkeypatch.setattr(
        "tracesvc.service.ClickHouseClient", lambda _settings: clickhouse
    )
    monkeypatch.setattr("tracesvc.service.create_tables", lambda _client: None)

    started: list[TraceService] = []

    async def _make(**overrides) -> TraceService:
        settings = TraceSettings(
            **{"batch_size": 3, "flush_interval_sec": 0.05, **overrides}
        )
        svc = TraceService(settings)
        await svc.start()
        started.append(svc)
        return svc

    yield _make

    for svc in started:
        if svc._workers:
            await svc.stop()


@pytest_asyncio.fixture
async def service(make_service) -> TraceService:
    return await make_service()


def _mock_grpc_server() -> Mock:
    """a grpc server whose wait_for_termination never returns.

    nothing but a signal can then end the serve loop, which is what the
    shutdown tests are about.
    """
    server = Mock()
    server.add_insecure_port = Mock()
    server.add_generic_rpc_handlers = Mock()
    server.start = AsyncMock()
    server.stop = AsyncMock()
    server.wait_for_termination = AsyncMock(side_effect=asyncio.Event().wait)
    return server


async def _await_serving(server: Mock, task: asyncio.Task) -> None:
    for _ in range(200):
        if server.start.await_count:
            return
        await asyncio.sleep(0.005)
    task.cancel()
    raise AssertionError("serve() did not start the grpc server")


@pytest.fixture
def serving(monkeypatch):
    """run serve() in the background with its service and grpc server mocked."""

    async def _start(settings):
        service = AsyncMock()
        server = _mock_grpc_server()

        monkeypatch.setattr(server_module, "TraceService", Mock(return_value=service))
        monkeypatch.setattr(server_module, "build_server", Mock(return_value=server))

        task = asyncio.create_task(server_module.serve(settings))
        await _await_serving(server, task)
        return service, server, task

    return _start


@pytest.fixture
def serving_live(redis_server, clickhouse, monkeypatch):
    """run serve() against a real TraceService, with only grpc and clickhouse faked.

    the workers, consumers and buffers are the production ones, so a signal has
    to travel the whole way to their drain for buffered rows to be persisted.
    """

    async def _start(**overrides):
        monkeypatch.setattr(
            "tracesvc.service.ClickHouseClient", lambda _settings: clickhouse
        )
        monkeypatch.setattr("tracesvc.service.create_tables", lambda _client: None)

        server = _mock_grpc_server()
        monkeypatch.setattr(server_module, "build_server", Mock(return_value=server))

        settings = TraceSettings(
            **{"batch_size": 100, "flush_interval_sec": 60.0, **overrides}
        )
        task = asyncio.create_task(server_module.serve(settings))
        await _await_serving(server, task)
        return task

    return _start
