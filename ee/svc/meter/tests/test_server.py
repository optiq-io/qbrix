"""serve() has to reach its teardown when the process is signalled.

meter is the least exposed of the four: it acks only after stripe accepts a
bucket, so a hard kill replays safely. what it still loses is the drain of an
in-flight bucket and a clean consumer close, and it waits out the full
termination grace on every rollout before being SIGKILLed.
"""

from __future__ import annotations

import asyncio
import os
import signal

from metersvc.config import MeterSettings


class TestShutdownSignal:
    async def test_sigterm_runs_teardown(self, serving):
        service, server, task = await serving(MeterSettings())

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        service.stop.assert_awaited_once()
        server.stop.assert_awaited_once_with(grace=20)

    async def test_sigint_runs_teardown(self, serving):
        service, _, task = await serving(MeterSettings())

        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.wait_for(task, timeout=5)

        service.stop.assert_awaited_once()

    async def test_grpc_stops_before_the_service(self, serving):
        order = []
        service, server, task = await serving(MeterSettings())
        server.stop.side_effect = lambda grace: order.append("server")
        service.stop.side_effect = lambda: order.append("service")

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        assert order == ["server", "service"]

    async def test_binds_the_configured_address(self, serving):
        _, server, task = await serving(MeterSettings(grpc_port=50096))

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        server.add_insecure_port.assert_called_once_with("0.0.0.0:50096")
