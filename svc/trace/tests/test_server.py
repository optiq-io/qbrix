"""serve() has to reach its teardown when the process is signalled.

trace is the service with unrecoverable loss on a hard kill: its batches are
buffered in memory, and on qbrix:feedback cortex's ack may already have deleted
the entries from the stream, so the drain on stop() is their last chance. that
drain is only reachable if wait_for_termination() yields to a signal.
"""

from __future__ import annotations

import asyncio
import os
import signal

import pytest

from qbrixstore.stream import topology

from tracesvc.config import TraceSettings

from trace_factories import make_selection


async def wait_for_pending(control, spec, count: int, timeout: float = 5.0) -> None:
    """wait until entries have been read into the group's pending list.

    read but unacked is what "buffered in the worker" looks like from outside
    the process.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if (await control.xpending(spec.name, "trace"))["pending"] == count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{count} entries were not read within {timeout}s")


class TestShutdownSignal:
    async def test_sigterm_runs_teardown(self, serving):
        service, server, task = await serving(TraceSettings())

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        service.stop.assert_awaited_once()
        server.stop.assert_awaited_once_with(grace=20)

    async def test_sigint_runs_teardown(self, serving):
        service, _, task = await serving(TraceSettings())

        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.wait_for(task, timeout=5)

        service.stop.assert_awaited_once()

    async def test_grpc_stops_before_the_service(self, serving):
        order = []
        service, server, task = await serving(TraceSettings())
        server.stop.side_effect = lambda grace: order.append("server")
        service.stop.side_effect = lambda: order.append("service")

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        assert order == ["server", "service"]

    async def test_binds_the_configured_address(self, serving):
        _, server, task = await serving(TraceSettings(grpc_port=50097))

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        server.add_insecure_port.assert_called_once_with("0.0.0.0:50097")


@pytest.mark.integration
class TestSigtermFlushesBufferedRows:
    """the acceptance criterion: rows buffered but not yet flushed must land.

    batch_size and flush_interval_sec are set so that nothing flushes on its own
    within the test — if the rows reach clickhouse, the signal is what put them
    there.
    """

    async def test_buffered_rows_reach_clickhouse(
        self, serving_live, control, clickhouse
    ):
        task = await serving_live()

        for _ in range(2):
            await control.xadd(topology.SELECTION.name, make_selection().to_dict())
        await wait_for_pending(control, topology.SELECTION, 2)
        assert clickhouse.inserts == []

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        assert len(clickhouse.selection) == 2

    async def test_clickhouse_is_closed_after_the_flush(
        self, serving_live, control, clickhouse
    ):
        task = await serving_live()
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())
        await wait_for_pending(control, topology.SELECTION, 1)

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        assert len(clickhouse.selection) == 1
        assert clickhouse.closed
