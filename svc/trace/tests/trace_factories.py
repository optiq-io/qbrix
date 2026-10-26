from __future__ import annotations

import asyncio
from typing import Sequence

from qbrixstore.event import AuditEvent
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import MetricEvent
from qbrixstore.event import SelectionEvent


class FakeClickHouse:
    """records what would have been written, and can be made to fail.

    inserts are synchronous in the real client too, so this matches the call
    shape trace uses.
    """

    def __init__(self) -> None:
        self.selection: list[SelectionEvent] = []
        self.feedback: list[FeedbackEvent] = []
        self.audit: list[AuditEvent] = []
        self.metric: list[MetricEvent] = []
        self.ledger_ms: dict[str, list[int]] = {"selection": [], "metric": []}
        self.inserts: list[tuple[str, int]] = []
        self.fail_next = 0
        self.closed = False
        # create_tables() is handed this; the tests stub the call itself out
        self.client = object()

    def connect(self, create_database: bool = True) -> None:
        pass

    def _record(self, kind: str, events: Sequence) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError(f"clickhouse insert failed ({kind})")
        getattr(self, kind).extend(events)
        self.inserts.append((kind, len(events)))

    def insert_selection_events(
        self, events: Sequence[SelectionEvent], ledger_ms: Sequence[int]
    ) -> None:
        self._record("selection", events)
        self.ledger_ms["selection"].extend(ledger_ms)

    def insert_feedback_events(self, events: Sequence[FeedbackEvent]) -> None:
        self._record("feedback", events)

    def insert_audit_events(self, events: Sequence[AuditEvent]) -> None:
        self._record("audit", events)

    def insert_metric_events(
        self, events: Sequence[MetricEvent], ledger_ms: Sequence[int]
    ) -> None:
        self._record("metric", events)
        self.ledger_ms["metric"].extend(ledger_ms)

    def health_check(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


def make_selection(tenant_id: str = "t1", experiment_id: str = "exp") -> SelectionEvent:
    return SelectionEvent(
        tenant_id=tenant_id,
        experiment_id=experiment_id,
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


def make_feedback(tenant_id: str = "t1", experiment_id: str = "exp") -> FeedbackEvent:
    return FeedbackEvent(
        tenant_id=tenant_id,
        experiment_id=experiment_id,
        request_id="req",
        arm_index=0,
        reward=1.0,
        context_id="ctx",
        context_vector=[],
        context_metadata={},
        timestamp_ms=1_000,
    )


def make_audit(tenant_id: str = "t1") -> AuditEvent:
    return AuditEvent(
        name="experiment.created",
        tenant_id=tenant_id,
        actor_id="",
        resource_type="experiment",
        resource_id="exp",
        payload={},
        timestamp_ms=1_000,
    )


def make_metric(tenant_id: str = "t1") -> MetricEvent:
    return MetricEvent(
        tenant_id=tenant_id,
        metric_id="m-1",
        metric_version="1.0",
        value=1.0,
        decisions=[
            {
                "decision_id": "dec-1",
                "loop_id": "loop-1",
                "cycle_id": "cyc-1",
                "option_index": 0,
                "opened_ms": 1_000,
            }
        ],
        unit="user-1",
        event_id="evt-1",
        at_ms=2_000,
        received_ms=2_000,
        source="outcome",
    )


async def wait_for(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")
