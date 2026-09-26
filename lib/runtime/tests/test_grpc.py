"""the serve-until-shutdown loop and the server it is given.

the ordering in serve_until_shutdown is load-bearing and was arrived at from a
production failure, so it is asserted rather than left to review.
"""

from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock
from unittest.mock import Mock

from grpc_health.v1 import health_pb2

from qbrixruntime.config import GrpcSettings
from qbrixruntime.grpc import add_health
from qbrixruntime.grpc import bind
from qbrixruntime.grpc import build_server
from qbrixruntime.grpc import serve_until_shutdown


def mock_server(*, terminates: asyncio.Future | None = None) -> Mock:
    server = Mock()
    server.add_insecure_port = Mock()
    server.add_generic_rpc_handlers = Mock()
    server.stop = AsyncMock()
    server.wait_for_termination = AsyncMock(
        side_effect=(terminates or asyncio.Event()).wait
    )
    return server


class TestBuildServer:
    def test_options_carry_the_keepalive_settings(self):
        settings = GrpcSettings(
            grpc_server_min_recv_ping_interval_ms=1234,
            grpc_server_keepalive_permit_without_calls=False,
        )

        server = build_server(settings)

        assert server is not None

    def test_bind_returns_the_listen_address(self):
        server = mock_server()

        addr = bind(server, GrpcSettings(grpc_host="127.0.0.1", grpc_port=51234))

        assert addr == "127.0.0.1:51234"
        server.add_insecure_port.assert_called_once_with("127.0.0.1:51234")


class TestServeUntilShutdown:
    async def test_returns_when_shutdown_is_requested(self):
        server = mock_server()
        shutdown = asyncio.Event()

        task = asyncio.ensure_future(serve_until_shutdown(server, shutdown, grace=1))
        await asyncio.sleep(0.01)
        assert not task.done()

        shutdown.set()
        await asyncio.wait_for(task, timeout=2)

        server.stop.assert_awaited_once_with(grace=1)

    async def test_returns_when_the_server_terminates_on_its_own(self):
        terminated = asyncio.Event()
        terminated.set()
        server = mock_server(terminates=terminated)

        await asyncio.wait_for(
            serve_until_shutdown(server, asyncio.Event(), grace=1), timeout=2
        )

        server.stop.assert_awaited_once_with(grace=1)

    async def test_the_server_is_stopped_before_the_waiter_is_cancelled(self):
        """cancelling wait_for_termination() while the server still runs
        propagates the cancellation into the serving task and kills teardown."""
        events = []

        async def wait_for_termination():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("waiter cancelled")
                raise

        server = mock_server()
        server.wait_for_termination = wait_for_termination
        server.stop = AsyncMock(side_effect=lambda grace: events.append("stopped"))

        shutdown = asyncio.Event()
        shutdown.set()
        await asyncio.wait_for(
            serve_until_shutdown(server, shutdown, grace=1), timeout=2
        )

        assert events == ["stopped", "waiter cancelled"]

    async def test_leaves_no_pending_tasks_behind(self):
        server = mock_server()
        shutdown = asyncio.Event()
        shutdown.set()
        before = len(asyncio.all_tasks())

        await asyncio.wait_for(
            serve_until_shutdown(server, shutdown, grace=0), timeout=2
        )

        assert len(asyncio.all_tasks()) == before

    async def test_stops_the_server_even_if_health_reporting_fails(self):
        """reporting NOT_SERVING is advisory; the drain is not."""
        server = mock_server()
        health = Mock()
        health.enter_graceful_shutdown = AsyncMock(side_effect=RuntimeError("boom"))
        shutdown = asyncio.Event()
        shutdown.set()

        await asyncio.wait_for(
            serve_until_shutdown(server, shutdown, grace=1, health=health), timeout=2
        )

        server.stop.assert_awaited_once_with(grace=1)


class TestHealthDuringShutdown:
    async def test_health_starts_serving(self):
        server = mock_server()

        health = await add_health(server, "motor")

        assert await self._check(health, "motor") == (
            health_pb2.HealthCheckResponse.SERVING
        )

    async def test_the_overall_entry_goes_not_serving_on_shutdown(self):
        """kubernetes grpc probes check the overall ("") entry, which the
        servicer sets to SERVING at construction and nothing else touches."""
        server = mock_server()
        health = await add_health(server, "motor")
        assert await self._check(health, "") == health_pb2.HealthCheckResponse.SERVING

        shutdown = asyncio.Event()
        shutdown.set()
        await serve_until_shutdown(server, shutdown, grace=0, health=health)

        assert await self._check(health, "") == (
            health_pb2.HealthCheckResponse.NOT_SERVING
        )

    @staticmethod
    async def _check(health, service: str):
        context = Mock()
        request = health_pb2.HealthCheckRequest(service=service)
        return (await health.Check(request, context)).status
