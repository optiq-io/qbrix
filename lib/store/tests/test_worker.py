"""unit tests for StreamWorker, the loop all five consumers used to hand-roll."""

from __future__ import annotations

import asyncio

import pytest

from qbrixstore.config import RedisSettings
from qbrixstore.event import AuditEvent
from qbrixstore.event import SelectionEvent
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.stream import topology
from qbrixstore.stream.worker import StreamWorker

pytestmark = pytest.mark.integration


def make_selection(tenant_id: str = "t1") -> SelectionEvent:
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


class Handler:
    """records every batch it is handed, and acks according to `mode`."""

    def __init__(self, mode: str = "all", fail_times: int = 0):
        self.mode = mode
        self.fail_times = fail_times
        self.batches: list[list[tuple[str, object]]] = []
        self.calls = 0

    @property
    def seen_ids(self) -> list[str]:
        return [mid for batch in self.batches for mid, _ in batch]

    async def __call__(self, batch):
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("handler boom")
        self.batches.append(list(batch))
        if self.mode == "none":
            return []
        if self.mode == "first":
            return [batch[0][0]] if batch else []
        return [mid for mid, _ in batch]


async def make_worker(
    spec=topology.SELECTION,
    group: str = "trace",
    handler: Handler | None = None,
    **kwargs,
) -> tuple[StreamWorker, Handler]:
    consumer = RedisStreamConsumer(
        spec, group, settings=RedisSettings(), consumer_name="w0"
    )
    await consumer.connect()
    handler = handler or Handler()
    return StreamWorker(consumer, handler, **kwargs), handler


async def wait_for(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


async def run_until(worker: StreamWorker, predicate) -> None:
    await worker.start()
    try:
        await wait_for(predicate)
    finally:
        await worker.stop()


class TestFlushCadence:
    async def test_no_interval_flushes_every_non_empty_read(
        self, redis_server, control
    ):
        """cortex's cadence: dispatch as soon as anything arrives."""
        worker, handler = await make_worker(batch_size=100, flush_interval_sec=0)
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: handler.calls >= 1)

        assert len(handler.batches[0]) == 1

    async def test_no_interval_never_calls_the_handler_while_idle(
        self, redis_server, control
    ):
        worker, handler = await make_worker(flush_interval_sec=0)

        await worker.start()
        await asyncio.sleep(0.2)
        await worker.stop()

        assert handler.calls == 0

    async def test_interval_flushes_once_the_batch_fills(self, redis_server, control):
        worker, handler = await make_worker(batch_size=3, flush_interval_sec=60)
        for _ in range(3):
            await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: handler.calls >= 1)

        assert len(handler.batches[0]) == 3

    async def test_interval_flushes_a_partial_batch_when_it_elapses(
        self, redis_server, control
    ):
        """trace's cadence: a partial batch still lands within the interval."""
        worker, handler = await make_worker(batch_size=500, flush_interval_sec=0.05)
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: handler.batches)

        assert len(handler.batches[0]) == 1

    async def test_a_batch_never_exceeds_batch_size(self, redis_server, control):
        worker, handler = await make_worker(batch_size=2, flush_interval_sec=60)
        for _ in range(6):
            await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: len(handler.seen_ids) == 6)

        assert all(len(batch) <= 2 for batch in handler.batches)


class TestTimeDrivenHandler:
    """the contract meter depends on.

    a bucket must be closed and emitted on schedule whether or not selections
    arrived; if the handler only ran on non-empty batches, a tenant that went
    quiet would never have its final bucket billed.
    """

    async def test_interval_invokes_the_handler_with_an_empty_batch(
        self, redis_server, control
    ):
        worker, handler = await make_worker(batch_size=500, flush_interval_sec=0.02)

        await run_until(worker, lambda: handler.calls >= 2)

        assert handler.batches[0] == []


class TestAckContract:
    async def test_returned_ids_are_acked(self, redis_server, control):
        worker, handler = await make_worker(flush_interval_sec=0)
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: handler.calls >= 1)

        pending = await control.xpending(topology.SELECTION.name, "trace")
        assert pending["pending"] == 0

    async def test_an_empty_return_leaves_the_entries_pending(
        self, redis_server, control
    ):
        """cortex and meter defer the ack; the worker must not ack behind them."""
        worker, handler = await make_worker(
            handler=Handler(mode="none"), flush_interval_sec=0
        )
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: handler.calls >= 1)

        pending = await control.xpending(topology.SELECTION.name, "trace")
        assert pending["pending"] == 1

    async def test_a_subset_return_acks_only_that_subset(self, redis_server, control):
        worker, handler = await make_worker(
            handler=Handler(mode="first"), batch_size=3, flush_interval_sec=60
        )
        for _ in range(3):
            await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: handler.calls >= 1)

        pending = await control.xpending(topology.SELECTION.name, "trace")
        assert pending["pending"] == 2

    async def test_delete_on_ack_follows_the_registry(self, redis_server, control):
        """audit has one group, so an ack deletes; selection has two, so it does not."""
        worker, handler = await make_worker(
            spec=topology.AUDIT, group="trace", flush_interval_sec=0
        )
        await control.xadd(topology.AUDIT.name, make_audit().to_dict())

        await run_until(worker, lambda: handler.calls >= 1)

        assert await control.xlen(topology.AUDIT.name) == 0

    async def test_fanned_out_stream_keeps_the_entry(self, redis_server, control):
        worker, handler = await make_worker(flush_interval_sec=0)
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: handler.calls >= 1)

        assert await control.xlen(topology.SELECTION.name) == 1


class TestHandlerFailure:
    async def test_a_raising_handler_keeps_the_batch_and_retries_it(
        self, redis_server, control
    ):
        worker, handler = await make_worker(
            handler=Handler(fail_times=1), batch_size=2, flush_interval_sec=0
        )
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await run_until(worker, lambda: handler.batches)

        # the same two entries, redelivered from the buffer rather than dropped
        assert len(handler.batches[0]) == 2
        pending = await control.xpending(topology.SELECTION.name, "trace")
        assert pending["pending"] == 0

    async def test_a_raising_handler_does_not_stop_the_worker(
        self, redis_server, control
    ):
        worker, handler = await make_worker(
            handler=Handler(fail_times=1), flush_interval_sec=0
        )
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await worker.start()
        await wait_for(lambda: handler.calls >= 2)
        assert worker._running is True

        # and it is still reading, not wedged on the entry that failed
        await control.xadd(topology.SELECTION.name, make_selection("after").to_dict())
        await wait_for(lambda: len(handler.seen_ids) == 2)
        await worker.stop()


class TestPoisonQuarantine:
    async def test_a_malformed_entry_does_not_stall_its_batch(
        self, redis_server, control
    ):
        """the defect that made one bad publish a total consumer outage.

        every hand-rolled loop decoded inside the read, so a single undecodable
        entry raised for the whole batch, and the loop re-read the same batch
        forever.
        """
        worker, handler = await make_worker(batch_size=3, flush_interval_sec=0.05)
        await control.xadd(topology.SELECTION.name, make_selection("good-1").to_dict())
        await control.xadd(topology.SELECTION.name, {"tenant_id": "only-this-field"})
        await control.xadd(topology.SELECTION.name, make_selection("good-2").to_dict())

        await run_until(worker, lambda: len(handler.seen_ids) == 2)

        tenants = [event.tenant_id for batch in handler.batches for _, event in batch]
        assert tenants == ["good-1", "good-2"]
        assert worker.quarantined == 1

    async def test_a_quarantined_entry_is_acked_out_of_the_pel(
        self, redis_server, control
    ):
        """it will never decode, so leaving it pending would strand it forever."""
        worker, handler = await make_worker(flush_interval_sec=0.05)
        await control.xadd(topology.SELECTION.name, {"tenant_id": "only-this-field"})

        await run_until(worker, lambda: worker.quarantined == 1)

        pending = await control.xpending(topology.SELECTION.name, "trace")
        assert pending["pending"] == 0

    async def test_an_unparseable_collection_field_is_quarantined(
        self, redis_server, control
    ):
        """the shape of a past regression: a field that is not json."""
        payload = make_selection().to_dict()
        payload["context_vector"] = "None"

        worker, handler = await make_worker(flush_interval_sec=0.05)
        await control.xadd(topology.SELECTION.name, payload)

        await run_until(worker, lambda: worker.quarantined == 1)

        assert handler.seen_ids == []

    async def test_the_loop_advances_past_a_poison_entry(self, redis_server, control):
        worker, handler = await make_worker(flush_interval_sec=0.05)
        await control.xadd(topology.SELECTION.name, {"tenant_id": "only-this-field"})

        await worker.start()
        await wait_for(lambda: worker.quarantined == 1)
        await control.xadd(topology.SELECTION.name, make_selection("after").to_dict())
        await wait_for(lambda: len(handler.seen_ids) == 1)
        await worker.stop()

        assert handler.batches[-1][0][1].tenant_id == "after"


class TestPendingRecovery:
    async def test_entries_stranded_in_the_pel_are_reclaimed(
        self, redis_server, control
    ):
        """what trace never did: reclaim what a dead incarnation left behind."""
        await control.xadd(
            topology.SELECTION.name, make_selection("stranded").to_dict()
        )

        worker, handler = await make_worker(flush_interval_sec=0)
        # a previous incarnation of this consumer read the entry and died
        await control.xreadgroup("trace", "w0", {topology.SELECTION.name: ">"})
        assert (await control.xpending(topology.SELECTION.name, "trace"))[
            "pending"
        ] == 1

        await run_until(worker, lambda: handler.batches)

        tenants = [event.tenant_id for batch in handler.batches for _, event in batch]
        assert tenants == ["stranded"]
        assert (await control.xpending(topology.SELECTION.name, "trace"))[
            "pending"
        ] == 0

    async def test_recovery_terminates_when_the_handler_defers_the_ack(
        self, redis_server, control
    ):
        """the cursor is what makes this terminate.

        cortex and meter leave reclaimed entries in the PEL, so a sweep that
        restarted from 0-0 each time would reclaim them forever and never reach
        the read loop.
        """
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())
        worker, handler = await make_worker(
            handler=Handler(mode="none"), batch_size=1, flush_interval_sec=0
        )
        await control.xreadgroup("trace", "w0", {topology.SELECTION.name: ">"})

        await asyncio.wait_for(worker._recover_pending(), timeout=2.0)

        assert handler.calls == 1

    async def test_recovery_quarantines_undecodable_pending_entries(
        self, redis_server, control
    ):
        await control.xadd(topology.SELECTION.name, {"tenant_id": "only-this-field"})
        worker, handler = await make_worker(flush_interval_sec=0)
        await control.xreadgroup("trace", "w0", {topology.SELECTION.name: ">"})

        await asyncio.wait_for(worker._recover_pending(), timeout=2.0)

        assert worker.quarantined == 1
        assert (await control.xpending(topology.SELECTION.name, "trace"))[
            "pending"
        ] == 0

    async def test_nothing_pending_is_a_no_op(self, redis_server, control):
        worker, handler = await make_worker(flush_interval_sec=0)

        await asyncio.wait_for(worker._recover_pending(), timeout=2.0)

        assert handler.calls == 0


class TestDrainOnStop:
    """the buffer is memory only, so stop() is the last chance to persist it.

    trace is the only service with unrecoverable loss on a
    hard kill, precisely because this flush is all that stands between buffered
    rows and nothing.
    """

    async def test_stop_flushes_the_buffered_batch(self, redis_server, control):
        worker, handler = await make_worker(batch_size=500, flush_interval_sec=60)
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await worker.start()
        await wait_for(lambda: worker.buffered == 1)
        assert handler.calls == 0

        await worker.stop()

        assert len(handler.batches[0]) == 1
        assert (await control.xpending(topology.SELECTION.name, "trace"))[
            "pending"
        ] == 0

    async def test_stop_is_idempotent(self, redis_server):
        worker, handler = await make_worker(flush_interval_sec=0)
        await worker.start()
        await worker.stop()
        await worker.stop()

    async def test_stop_without_start_is_inert(self, redis_server):
        worker, handler = await make_worker(flush_interval_sec=0)
        await worker.stop()
        assert handler.calls == 0

    async def test_start_twice_runs_one_loop(self, redis_server):
        worker, handler = await make_worker(flush_interval_sec=0)
        await worker.start()
        first = worker._task
        await worker.start()
        assert worker._task is first
        await worker.stop()
