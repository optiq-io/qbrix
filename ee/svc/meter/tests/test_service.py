from __future__ import annotations

import time
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from qbrixstore.event import SelectionEvent

from metersvc.config import MeterSettings
from metersvc.customer import CustomerCache
from metersvc.service import BucketAggregator
from metersvc.service import MeterService


def make_event(tenant_id: str, timestamp_ms: int) -> SelectionEvent:
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
        timestamp_ms=timestamp_ms,
        policy="beta_ts",
    )


BUCKET_MS = 60_000


class TestBucketAggregator:
    def test_sums_per_tenant_and_bucket(self):
        agg = BucketAggregator(BUCKET_MS)
        # two events in the same 60s bucket for tenant a
        agg.add("1-0", make_event("a", 1_000))
        agg.add("2-0", make_event("a", 59_000))
        # one event in the next bucket for tenant a
        agg.add("3-0", make_event("a", 61_000))
        # one event for tenant b in the first bucket
        agg.add("4-0", make_event("b", 5_000))

        assert agg.pop(("a", 0)) == {"count": 2, "message_ids": ["1-0", "2-0"]}
        assert agg.pop(("a", 1)) == {"count": 1, "message_ids": ["3-0"]}
        assert agg.pop(("b", 0)) == {"count": 1, "message_ids": ["4-0"]}

    def test_bucket_derived_from_event_timestamp(self):
        agg = BucketAggregator(BUCKET_MS)
        agg.add("1-0", make_event("a", 123_456))
        # 123456 // 60000 == 2
        assert ("a", 2) in [k for k in agg._buckets]

    def test_closed_keys_respects_grace(self):
        agg = BucketAggregator(BUCKET_MS)
        agg.add("1-0", make_event("a", 0))  # bucket 0 ends at 60_000
        grace_ms = 30_000

        # now just after the bucket end but within grace -> not closed
        assert agg.closed_keys(now_ms=80_000, grace_ms=grace_ms) == []
        # now past end + grace -> closed
        assert agg.closed_keys(now_ms=95_000, grace_ms=grace_ms) == [("a", 0)]


def _service_with_mocks(paid: bool = True, emit_ok: bool = True) -> MeterService:
    svc = MeterService(MeterSettings(bucket_seconds=60, close_grace_seconds=30))
    svc._consumer = AsyncMock()
    svc._emitter = MagicMock()
    svc._emitter.emit.return_value = emit_ok
    svc._customers = AsyncMock()
    svc._customers.get.return_value = "cus_123" if paid else None
    return svc


class TestEmitBucket:
    async def test_paid_tenant_emits_then_acks(self):
        svc = _service_with_mocks(paid=True, emit_ok=True)
        svc._aggregator.add("1-0", make_event("t1", 1_000))
        svc._aggregator.add("2-0", make_event("t1", 2_000))

        await svc._emit_bucket("t1", 0)

        svc._emitter.emit.assert_called_once_with(
            stripe_customer_id="cus_123",
            value=2,
            identifier="t1:0",
            timestamp=60,
        )
        svc._consumer.ack.assert_awaited_once_with(["1-0", "2-0"])
        assert len(svc._aggregator) == 0

    async def test_unpaid_tenant_acks_without_emit(self):
        svc = _service_with_mocks(paid=False)
        svc._aggregator.add("1-0", make_event("free", 1_000))

        await svc._emit_bucket("free", 0)

        svc._emitter.emit.assert_not_called()
        svc._consumer.ack.assert_awaited_once_with(["1-0"])
        assert len(svc._aggregator) == 0

    async def test_stripe_failure_does_not_ack_and_retries(self):
        svc = _service_with_mocks(paid=True, emit_ok=False)
        svc._aggregator.add("1-0", make_event("t1", 1_000))

        await svc._emit_bucket("t1", 0)

        svc._emitter.emit.assert_called_once()
        svc._consumer.ack.assert_not_awaited()
        # bucket is kept for retry
        assert svc._aggregator.pop(("t1", 0)) == {"count": 1, "message_ids": ["1-0"]}

    async def test_idempotency_identifier_is_tenant_bucket(self):
        svc = _service_with_mocks(paid=True, emit_ok=True)
        svc._aggregator.add("9-0", make_event("t2", 3 * BUCKET_MS + 500))

        await svc._emit_bucket("t2", 3)

        _, kwargs = svc._emitter.emit.call_args
        assert kwargs["identifier"] == "t2:3"


class TestCustomerCache:
    async def test_caches_positive_result(self, mocker):
        customers = CustomerCache(maxsize=100, ttl=60)
        load = mocker.patch.object(customers, "_load", AsyncMock(return_value="cus_1"))

        assert await customers.get("t1") == "cus_1"
        assert await customers.get("t1") == "cus_1"
        load.assert_awaited_once()  # second call served from cache

    async def test_caches_negative_result(self, mocker):
        customers = CustomerCache(maxsize=100, ttl=60)
        load = mocker.patch.object(customers, "_load", AsyncMock(return_value=None))

        assert await customers.get("free") is None
        assert await customers.get("free") is None
        # a cached None is not re-loaded (distinguished from a miss)
        load.assert_awaited_once()


class TestHandler:
    """the seam StreamWorker drives: aggregate, close what is due, ack nothing.

    reclaiming the PEL is the worker's job now and is tested generically in
    lib/store/tests/test_worker.py.
    """

    async def test_aggregates_the_batch_and_defers_the_ack(self):
        svc = _service_with_mocks()
        # a timestamp in the current bucket, so it is not yet due to be emitted
        now_ms = int(time.time() * 1000)
        bucket = now_ms // 60_000

        acked = await svc._handle(
            [("1-0", make_event("t1", now_ms)), ("2-0", make_event("t1", now_ms))]
        )

        assert list(acked) == []
        assert svc._aggregator.pop(("t1", bucket)) == {
            "count": 2,
            "message_ids": ["1-0", "2-0"],
        }
        svc._consumer.ack.assert_not_awaited()

    async def test_an_empty_batch_still_closes_a_due_bucket(self):
        """why the worker calls the handler on every flush boundary, empty or not.

        closing a bucket is wall-clock work: a tenant that stops sending
        selections must still have its last bucket emitted, and if the handler
        only ran on non-empty batches it never would be.
        """
        svc = _service_with_mocks()
        svc._aggregator.add("1-0", make_event("t1", 1_000))

        await svc._handle([])

        svc._emitter.emit.assert_called_once()
        svc._consumer.ack.assert_awaited_once_with(["1-0"])
