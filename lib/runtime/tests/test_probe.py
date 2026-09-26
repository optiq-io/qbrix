"""the container health probe against a real grpc server.

the probe replaces a binary in every service image, so what it reports for a
serving, a draining and an absent server is pinned end to end.
"""

from __future__ import annotations

import asyncio
import socket

import pytest
from grpc_health.v1 import health_pb2

from qbrixruntime.config import GrpcSettings
from qbrixruntime.grpc import add_health
from qbrixruntime.grpc import bind
from qbrixruntime.grpc import build_server
from qbrixruntime.probe import main


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def server():
    port = free_port()
    server = build_server(GrpcSettings(grpc_host="127.0.0.1", grpc_port=port))
    target = bind(server, GrpcSettings(grpc_host="127.0.0.1", grpc_port=port))
    health = await add_health(server, "qbrix.test.Service")
    await server.start()
    yield target, health
    await server.stop(None)


async def probe(*argv: str) -> int:
    return await asyncio.to_thread(main, list(argv))


class TestProbe:
    async def test_a_serving_server_passes(self, server):
        target, _ = server

        assert await probe(target) == 0

    async def test_a_draining_server_fails(self, server):
        target, health = server
        await health.set("", health_pb2.HealthCheckResponse.NOT_SERVING)

        assert await probe(target) == 1

    async def test_no_server_fails(self):
        assert await probe(f"127.0.0.1:{free_port()}") == 1

    async def test_a_missing_target_is_a_usage_error(self):
        assert await probe() == 2
