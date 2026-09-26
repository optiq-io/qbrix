"""tests for trace's three stream consumers, now running on StreamWorker.

these began as characterisation tests against the three hand-rolled loops (see the
commit that added them) and are carried forward against the worker, so the
batch/flush/ack mechanics are asserted to be unchanged. two behaviours are new and
deliberate: the PEL is recovered on startup, and an undecodable entry is
quarantined instead of stalling its batch forever.

what is still *not* asserted is that every feedback event reaches clickhouse.
cortex consumes qbrix:feedback with delete_on_ack=True, so it can XDEL entries
trace has not read. that is a known durability hole, not covered here.
"""

from __future__ import annotations

import asyncio

import pytest

from qbrixstore.stream import topology

from trace_factories import make_audit
from trace_factories import make_feedback
from trace_factories import make_selection
from trace_factories import wait_for

pytestmark = pytest.mark.integration


async def pending(control, spec) -> int:
    return (await control.xpending(spec.name, "trace"))["pending"]


class TestBatching:
    async def test_flushes_when_the_batch_fills(self, service, control, clickhouse):
        for _ in range(3):
            await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await wait_for(lambda: len(clickhouse.selection) == 3)

        assert ("selection", 3) in clickhouse.inserts

    async def test_flushes_a_partial_batch_once_the_interval_elapses(
        self, service, control, clickhouse
    ):
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await wait_for(lambda: len(clickhouse.selection) == 1)

        assert clickhouse.inserts == [("selection", 1)]

    async def test_does_not_insert_while_nothing_arrives(self, service, clickhouse):
        """the handler is called on every flush boundary, empty batch included —
        it must not turn that into an empty insert."""
        await asyncio.sleep(0.3)

        assert clickhouse.inserts == []

    async def test_a_batch_never_exceeds_batch_size(self, service, control, clickhouse):
        for _ in range(10):
            await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await wait_for(lambda: len(clickhouse.selection) == 10)

        assert all(count <= 3 for _, count in clickhouse.inserts)


class TestAcking:
    async def test_entries_are_acked_after_the_insert(
        self, service, control, clickhouse
    ):
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await wait_for(lambda: len(clickhouse.selection) == 1)
        await wait_for(lambda: True)

        assert await pending(control, topology.SELECTION) == 0

    async def test_a_failed_insert_retains_the_batch_and_retries(
        self, service, control, clickhouse
    ):
        clickhouse.fail_next = 1
        for _ in range(3):
            await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await wait_for(lambda: len(clickhouse.selection) == 3)

        # the same three rows land exactly once, on the retry
        assert clickhouse.inserts == [("selection", 3)]
        assert await pending(control, topology.SELECTION) == 0

    async def test_fanned_out_stream_keeps_the_entry_after_ack(
        self, service, control, clickhouse
    ):
        """selection has two groups, so an ack must not delete the entry."""
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())

        await wait_for(lambda: len(clickhouse.selection) == 1)

        assert await control.xlen(topology.SELECTION.name) == 1

    async def test_single_group_stream_deletes_the_entry_on_ack(
        self, service, control, clickhouse
    ):
        """audit has one group, so an ack deletes it."""
        await control.xadd(topology.AUDIT.name, make_audit().to_dict())

        await wait_for(lambda: len(clickhouse.audit) == 1)
        await wait_for(lambda: True)

        assert await control.xlen(topology.AUDIT.name) == 0


class TestAllThreeStreams:
    async def test_each_stream_reaches_its_own_table(
        self, service, control, clickhouse
    ):
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())
        await control.xadd(topology.FEEDBACK.name, make_feedback().to_dict())
        await control.xadd(topology.AUDIT.name, make_audit().to_dict())

        await wait_for(
            lambda: len(clickhouse.selection) == 1
            and len(clickhouse.feedback) == 1
            and len(clickhouse.audit) == 1
        )

    async def test_a_worker_runs_per_stream(self, service):
        assert [worker.name for worker in service._workers] == [
            "qbrix:selection/trace",
            "qbrix:feedback/trace",
            "qbrix:audit/trace",
        ]


class TestStats:
    async def test_stats_count_per_tenant_and_experiment(
        self, service, control, clickhouse
    ):
        for tenant, experiment in [("t1", "exp-a"), ("t1", "exp-a"), ("t2", "exp-b")]:
            await control.xadd(
                topology.SELECTION.name, make_selection(tenant, experiment).to_dict()
            )

        await wait_for(lambda: len(clickhouse.selection) == 3)

        stats = {(s["tenant_id"], s["experiment_id"]): s for s in service.get_stats()}
        assert stats[("t1", "exp-a")]["selections"] == 2
        assert stats[("t2", "exp-b")]["selections"] == 1
        assert stats[("t1", "exp-a")]["last_write"] > 0

    async def test_audit_stats_are_keyed_per_tenant(self, service, control, clickhouse):
        await control.xadd(topology.AUDIT.name, make_audit("t1").to_dict())

        await wait_for(lambda: len(clickhouse.audit) == 1)

        stats = {(s["tenant_id"], s["experiment_id"]): s for s in service.get_stats()}
        assert stats[("t1", "audit")]["audit"] == 1


class TestStopDrainsBufferedRows:
    """the buffer moved from TraceService into StreamWorker; the guarantee did not.

    this is the only unrecoverable loss in the system: the rows
    exist in memory only, and on qbrix:feedback cortex's ack may already have
    deleted them from the stream.
    """

    async def test_stop_flushes_rows_still_buffered(
        self, make_service, control, clickhouse
    ):
        # an interval long enough that nothing flushes on its own
        service = await make_service(batch_size=500, flush_interval_sec=60)
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())
        await wait_for(lambda: service._workers[0].buffered == 1)
        assert clickhouse.inserts == []

        await service.stop()

        assert len(clickhouse.selection) == 1
        assert await pending(control, topology.SELECTION) == 0

    async def test_stop_drains_all_three_streams(
        self, make_service, control, clickhouse
    ):
        service = await make_service(batch_size=500, flush_interval_sec=60)
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())
        await control.xadd(topology.FEEDBACK.name, make_feedback().to_dict())
        await control.xadd(topology.AUDIT.name, make_audit().to_dict())
        await wait_for(lambda: all(w.buffered == 1 for w in service._workers))

        await service.stop()

        assert (
            len(clickhouse.selection),
            len(clickhouse.feedback),
            len(clickhouse.audit),
        ) == (1, 1, 1)

    async def test_stop_closes_clickhouse(self, service, clickhouse):
        await service.stop()
        assert clickhouse.closed is True

    async def test_a_failed_flush_on_stop_does_not_raise(
        self, make_service, control, clickhouse
    ):
        service = await make_service(batch_size=500, flush_interval_sec=60)
        await control.xadd(topology.SELECTION.name, make_selection().to_dict())
        await wait_for(lambda: service._workers[0].buffered == 1)
        clickhouse.fail_next = 1

        await service.stop()

        assert clickhouse.closed is True


class TestPendingRecovery:
    """trace reclaims its PEL on start.

    XREADGROUP with ">" only returns undelivered entries, so without the reclaim
    anything a previous incarnation read but did not ack is stranded permanently.
    """

    async def test_entries_stranded_by_a_crash_are_recovered(
        self, make_service, control, clickhouse
    ):
        await control.xgroup_create(
            topology.SELECTION.name, "trace", id="0", mkstream=True
        )
        await control.xadd(
            topology.SELECTION.name, make_selection("stranded").to_dict()
        )
        # a previous incarnation read the entry and died before acking it
        await control.xreadgroup("trace", "worker-0", {topology.SELECTION.name: ">"})
        assert await pending(control, topology.SELECTION) == 1

        await make_service()

        await wait_for(lambda: len(clickhouse.selection) == 1)
        assert clickhouse.selection[0].tenant_id == "stranded"
        assert await pending(control, topology.SELECTION) == 0


class TestPoisonQuarantine:
    """new behaviour: one malformed entry used to stall its stream forever.

    decoding happened inside the read, so a single undecodable entry raised for the
    whole batch and the loop re-read that same batch on a 1s cycle, endlessly.
    """

    async def test_a_malformed_entry_does_not_stall_its_batch(
        self, service, control, clickhouse
    ):
        await control.xadd(topology.SELECTION.name, make_selection("good-1").to_dict())
        await control.xadd(topology.SELECTION.name, {"tenant_id": "only-this-field"})
        await control.xadd(topology.SELECTION.name, make_selection("good-2").to_dict())

        await wait_for(lambda: len(clickhouse.selection) == 2)

        assert [e.tenant_id for e in clickhouse.selection] == ["good-1", "good-2"]
        assert service._workers[0].quarantined == 1
        assert await pending(control, topology.SELECTION) == 0

    async def test_the_stream_keeps_moving_after_a_poison_entry(
        self, service, control, clickhouse
    ):
        await control.xadd(topology.SELECTION.name, {"tenant_id": "only-this-field"})
        await wait_for(lambda: service._workers[0].quarantined == 1)

        await control.xadd(topology.SELECTION.name, make_selection("after").to_dict())

        await wait_for(lambda: len(clickhouse.selection) == 1)
        assert clickhouse.selection[0].tenant_id == "after"
