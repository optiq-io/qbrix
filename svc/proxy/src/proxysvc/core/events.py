from __future__ import annotations

import asyncio

from qbrixlog import get_logger
from qbrixstore.config import RedisSettings
from qbrixstore.redis.streams import RedisStreamPublisher
from qbrixstore.stream import topology
from qbrixstore.event import AuditEvent
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent

from proxysvc.config import ProxySettings

logger = get_logger(__name__)


class EventEmitter:
    """proxy's outbound event egress.

    owns the three redis event streams — feedback, selection, audit — their
    lifecycle, ee-gating, best-effort publish, and uniform fire-and-forget
    dispatch with drain-on-stop.

    feedback is the learning-path signal and is always emitted; selection and
    audit are emitted only when something consumes them, and otherwise no-op.
    every stream is dispatched fire-and-forget so no emit ever blocks the
    request path; in-flight tasks are tracked and drained on stop().
    """

    def __init__(self, redis: RedisSettings, *, selection: bool, audit: bool):
        self._feedback = RedisStreamPublisher(topology.FEEDBACK, redis)
        self._selection = (
            RedisStreamPublisher(topology.SELECTION, redis) if selection else None
        )
        self._audit = RedisStreamPublisher(topology.AUDIT, redis) if audit else None
        self._inflight: set[asyncio.Task] = set()

    @classmethod
    def for_settings(
        cls, redis: RedisSettings, settings: ProxySettings
    ) -> EventEmitter:
        """selection feeds trace and metersvc; audit feeds trace only."""
        return cls(
            redis,
            selection=settings.ee_enabled or settings.analytics_enabled,
            audit=settings.analytics_enabled,
        )

    @property
    def selection_enabled(self) -> bool:
        """whether the selection stream is active.

        lets the hot path skip building selection events nobody consumes.
        """
        return self._selection is not None

    # lifecycle

    async def start(self) -> None:
        await self._feedback.connect()
        if self._selection:
            await self._selection.connect()
            logger.info("selection publisher connected")
        if self._audit:
            await self._audit.connect()
            logger.info("audit publisher connected")

    async def stop(self) -> None:
        await self.drain()
        await self._feedback.close()
        if self._selection:
            await self._selection.close()
        if self._audit:
            await self._audit.close()

    async def drain(self) -> None:
        """await all in-flight dispatch tasks (used by stop() and by tests)."""
        if self._inflight:
            await asyncio.gather(*tuple(self._inflight), return_exceptions=True)

    # dispatch primitive

    def dispatch(self, awaitable) -> None:
        """schedule an awaitable as a tracked fire-and-forget task."""
        task = asyncio.ensure_future(awaitable)
        self._inflight.add(task)
        task.add_done_callback(self._on_done)

    def _on_done(self, task: asyncio.Task) -> None:
        self._inflight.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("background event publish failed: %s", exc)

    # typed fire-and-forget emits
    #
    # the emitter constructs nothing — every method takes pre-built event(s) and
    # only routes/dispatches them. event construction (incl. timestamps) belongs
    # to the caller. emit_* batch their events into a single dispatched task.

    def emit_audit(self, *events: AuditEvent) -> None:
        self.dispatch(asyncio.gather(*(self._publish(self._audit, e) for e in events)))

    def emit_feedback(self, *events: FeedbackEvent) -> None:
        self.dispatch(
            asyncio.gather(*(self._publish(self._feedback, e) for e in events))
        )

    def emit_selection(self, *events: SelectionEvent) -> None:
        self.dispatch(
            asyncio.gather(*(self._publish(self._selection, e) for e in events))
        )

    @staticmethod
    async def _publish(publisher: RedisStreamPublisher | None, event) -> None:
        if not publisher:
            return
        try:
            await publisher.publish(event)
        except Exception as e:  # noqa
            logger.error("failed to publish %s: %s", type(event).__name__, e)
