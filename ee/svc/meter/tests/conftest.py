"""shared fixtures for metersvc tests."""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock
from unittest.mock import Mock

from metersvc import server as server_module


@pytest.fixture
def serving(monkeypatch):
    """run serve() in the background with its service and grpc server mocked.

    the mock server's wait_for_termination never returns, so nothing but a
    signal can end the serve loop — which is the whole point of these tests.
    """

    async def _start(settings):
        service = AsyncMock()

        server = Mock()
        server.add_insecure_port = Mock()
        server.add_generic_rpc_handlers = Mock()
        server.start = AsyncMock()
        server.stop = AsyncMock()
        server.wait_for_termination = AsyncMock(side_effect=asyncio.Event().wait)

        monkeypatch.setattr(server_module, "MeterService", Mock(return_value=service))
        monkeypatch.setattr(server_module, "build_server", Mock(return_value=server))

        task = asyncio.create_task(server_module.serve(settings))
        for _ in range(200):
            if server.start.await_count:
                return service, server, task
            await asyncio.sleep(0.005)
        task.cancel()
        raise AssertionError("serve() did not start the grpc server")

    return _start
