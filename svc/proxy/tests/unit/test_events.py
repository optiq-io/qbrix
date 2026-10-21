"""unit tests for the EventEmitter egress."""

from __future__ import annotations

import pytest

from qbrixstore.config import RedisSettings
from qbrixstore.event import AuditEvent
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent

from proxysvc.core.events import EventEmitter


class _SpyPublisher:
    """records published events; optionally raises to exercise best-effort."""

    def __init__(self, raises: bool = False) -> None:
        self.events: list = []
        self._raises = raises

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def publish(self, event) -> str:
        if self._raises:
            raise RuntimeError("stream down")
        self.events.append(event)
        return "id-1"


def _emitter(raises: bool = False) -> EventEmitter:
    em = EventEmitter(RedisSettings())
    em._feedback = _SpyPublisher(raises=raises)
    em._selection = _SpyPublisher(raises=raises)
    em._audit = _SpyPublisher(raises=raises)
    return em


def _audit_event(name: str = "pool.created") -> AuditEvent:
    return AuditEvent(
        name=name,
        tenant_id="t-1",
        actor_id="u-1",
        resource_type="pool",
        resource_id="pool-1",
        payload={"arm_count": 2},
        timestamp_ms=1,
    )


def _feedback_event(experiment_id: str = "exp-1") -> FeedbackEvent:
    return FeedbackEvent(
        tenant_id="t-1",
        experiment_id=experiment_id,
        request_id="req-1",
        arm_index=0,
        reward=1.0,
        context_id="ctx-1",
        context_vector=[],
        context_metadata={},
        timestamp_ms=1,
    )


def _selection_event() -> SelectionEvent:
    return SelectionEvent(
        tenant_id="t-1",
        experiment_id="exp-1",
        request_id="req-1",
        event_id="evt-1",
        arm_id="arm-1",
        arm_name="control",
        arm_index=0,
        is_default=False,
        context_id="ctx-1",
        context_vector=[],
        context_metadata={},
        timestamp_ms=1,
        policy="BetaTSPolicy",
    )


class TestSelectionEventSerialization:
    def test_event_id_round_trips(self):
        event = _selection_event()
        restored = SelectionEvent.from_dict(event.to_dict())
        assert restored.event_id == event.event_id == "evt-1"

    def test_missing_event_id_is_minted(self):
        # pre-deploy in-flight events lack the key; from_dict must mint one so
        # dedup still has an identity rather than crashing
        data = _selection_event().to_dict()
        del data["event_id"]
        restored = SelectionEvent.from_dict(data)
        assert restored.event_id


class TestEmitAudit:

    @pytest.mark.asyncio
    async def test_emit_audit_dispatches_event(self):
        em = _emitter()
        em.emit_audit(_audit_event(name="pool.created"))
        await em.drain()

        assert len(em._audit.events) == 1
        event = em._audit.events[0]
        assert isinstance(event, AuditEvent)
        assert event.name == "pool.created"
        assert event.resource_id == "pool-1"

    @pytest.mark.asyncio
    async def test_emit_audit_publishes_multiple(self):
        em = _emitter()
        em.emit_audit(_audit_event("pool.created"), _audit_event("pool.deleted"))
        await em.drain()

        assert len(em._audit.events) == 2
        assert {e.name for e in em._audit.events} == {"pool.created", "pool.deleted"}


class TestEmitFeedback:

    @pytest.mark.asyncio
    async def test_emit_feedback_single(self):
        em = _emitter()
        em.emit_feedback(_feedback_event())
        await em.drain()

        assert len(em._feedback.events) == 1

    @pytest.mark.asyncio
    async def test_emit_feedback_publishes_both_meta_events(self):
        em = _emitter()
        em.emit_feedback(_feedback_event("exp-1"), _feedback_event("meta-1"))
        await em.drain()

        assert len(em._feedback.events) == 2
        assert {e.experiment_id for e in em._feedback.events} == {"exp-1", "meta-1"}


class TestEmitSelection:

    @pytest.mark.asyncio
    async def test_emit_selection_single(self):
        em = _emitter()
        em.emit_selection(_selection_event())
        await em.drain()

        assert len(em._selection.events) == 1

    @pytest.mark.asyncio
    async def test_emit_selection_publishes_multiple(self):
        em = _emitter()
        em.emit_selection(_selection_event(), _selection_event())
        await em.drain()

        assert len(em._selection.events) == 2


class TestBestEffortAndLifecycle:

    @pytest.mark.asyncio
    async def test_publish_error_is_swallowed(self):
        em = _emitter(raises=True)
        # a failing publish must not surface to the caller
        em.emit_audit(_audit_event())
        em.emit_feedback(_feedback_event())
        await em.drain()

        assert em._audit.events == []
        assert em._feedback.events == []

    @pytest.mark.asyncio
    async def test_drain_clears_inflight(self):
        em = _emitter()
        em.emit_feedback(_feedback_event())
        em.emit_audit(_audit_event())
        await em.drain()

        assert em._inflight == set()

    @pytest.mark.asyncio
    async def test_close_drains_then_closes(self):
        em = _emitter()
        em.emit_feedback(_feedback_event())
        await em.stop()

        assert em._inflight == set()
        assert len(em._feedback.events) == 1
