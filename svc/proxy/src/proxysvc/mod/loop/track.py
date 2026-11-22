from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from qbrixlog import get_logger
from qbrixstore.event import MetricEvent
from qbrixstore.redis import OutcomeDisposition
from qbrixstore.redis import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.error import InvalidOutcomeError
from proxysvc.core.error import MetricNotFoundError
from proxysvc.core.error import TokenInvalidError
from proxysvc.core.events import EventEmitter
from proxysvc.mod.loop.outcome import check_event_id
from proxysvc.mod.loop.outcome import check_value
from proxysvc.mod.loop.outcome import count_earlier_cycle
from proxysvc.mod.loop.outcome import decision_ref
from proxysvc.mod.loop.outcome import earlier_cycle
from proxysvc.mod.loop.outcome import event_at_ms
from proxysvc.mod.loop.route import LoopRoute
from proxysvc.mod.loop.route import LoopRouteCache
from proxysvc.mod.loop.select import UNIT_MAX_LENGTH
from proxysvc.mod.loop.token import Decision
from proxysvc.mod.loop.token import DecisionToken
from proxysvc.mod.loop.token import DecisionsToken
from proxysvc.mod.metric.route import MetricRouteCache
from proxysvc.mod.metric.route import RouteMetric

logger = get_logger(__name__)

SOURCE = "track"
BATCH_MAX = 500


@dataclass(frozen=True)
class TrackEvent:
    """something that happened for a metric, with the decisions token the
    device carried or the unit it happened to."""

    metric: str
    value: Any
    decisions: str | None = None
    unit: str | None = None
    id: Any = None
    at: datetime | None = None


def _check_unit(unit: Any) -> str:
    if not isinstance(unit, str) or not unit.strip():
        raise InvalidOutcomeError(
            "an event needs the decisions it belongs to, or the unit it happened to"
        )
    if len(unit) > UNIT_MAX_LENGTH:
        raise InvalidOutcomeError(
            f"unit is at most {UNIT_MAX_LENGTH} characters, got {len(unit)}"
        )
    return unit


class LoopTrackService:
    """track(metric, value, {decisions, unit, id, at}): an event for a metric,
    credited to exactly the decisions it carries, or left for the sealer to
    match by its unit.

    an event that carries decisions is never matched by unit: when none of
    them is for a loop improving its metric, it is recorded with neither, so
    nothing can credit it. like outcome, nothing here reads postgres but the
    metric, and that through its cache.
    """

    def __init__(
        self,
        *,
        redis: RedisClient,
        routes: LoopRouteCache,
        metrics: MetricRouteCache,
        events: EventEmitter,
        settings: ProxySettings,
    ):
        self._redis = redis
        self._routes = routes
        self._metrics = metrics
        self._events = events
        self._settings = settings

    async def track(self, tenant_id: str, event: TrackEvent) -> dict:
        metric = await self._metrics.get(tenant_id, event.metric)
        if metric is None:
            raise MetricNotFoundError(f"no metric named {event.metric!r}")

        if event.decisions is None:
            unit = _check_unit(event.unit)
            carried = None
        else:
            unit = _check_unit(event.unit) if event.unit is not None else ""
            carried = await self._carried(tenant_id, event.decisions, metric)

        try:
            value = check_value(metric, event.value)
        except InvalidOutcomeError:
            self._events.dispatch(
                self._count_invalid(tenant_id, metric.id, [d for d, _ in carried or []])
            )
            raise

        now_ms = int(time.time() * 1000)
        event_id = check_event_id(event.id)
        at_ms = event_at_ms(event.at, now_ms)

        credited = None
        if carried is not None:
            credited = [(d, r) for d, r in carried if d.timestamp_ms <= at_ms]
            if not credited:
                unit = ""
                self._events.dispatch(self._count_unattributed(tenant_id, metric.id))

        self._events.emit_metric(
            MetricEvent(
                tenant_id=tenant_id,
                metric_id=metric.id,
                metric_version=metric.version,
                value=value,
                decisions=[decision_ref(d) for d, _ in credited or []],
                unit=unit,
                event_id=event_id,
                at_ms=at_ms,
                received_ms=now_ms,
                source=SOURCE,
            )
        )
        for cycle_id in {d.cycle_id for d, _ in credited or []}:
            self._events.dispatch(
                self._record_intake(tenant_id, cycle_id, metric.window_ms, now_ms)
            )
        for decision, route in credited or []:
            current = earlier_cycle(route, decision)
            if current is not None:
                self._events.dispatch(
                    count_earlier_cycle(self._redis, tenant_id, current)
                )
        return {
            "id": event_id,
            "at_ms": at_ms,
            "credited": len(credited) if credited is not None else None,
        }

    async def track_batch(
        self, tenant_id: str, events: list[TrackEvent]
    ) -> list[dict | Exception]:
        """each event's result, or the error that refused it, in order: one
        bad event never refuses the rest."""
        results: list[dict | Exception] = []
        for event in events:
            try:
                results.append(await self.track(tenant_id, event))
            except (InvalidOutcomeError, MetricNotFoundError, TokenInvalidError) as e:
                results.append(e)
        return results

    async def _carried(
        self, tenant_id: str, token: Any, metric: RouteMetric
    ) -> list[tuple[Decision, LoopRoute]]:
        """the decisions in a token whose loop improves this metric, each with
        its loop's route.

        an entry that doesn't verify in this workspace is dropped and counted;
        the event is refused only when none does. an entry made under another
        metric, or for a loop that no longer exists, is not this event's.
        """
        if not isinstance(token, str):
            raise TokenInvalidError("decisions must be the token decisions() returns")
        secret = self._settings.token_secret_bytes
        verified: list[Decision] = []
        refused = 0
        for entry in DecisionsToken.split(token):
            try:
                verified.append(DecisionToken.decode(secret, entry, tenant_id))
            except TokenInvalidError:
                refused += 1
        if refused:
            self._events.dispatch(self._count_invalid_tokens(tenant_id, refused))
        if not verified:
            raise TokenInvalidError("no decision in the token verifies")

        carried = []
        for decision in verified:
            if decision.metric_id != metric.id:
                continue
            route = await self._routes.get(tenant_id, decision.loop_id)
            if route is not None:
                carried.append((decision, route))
        return carried

    async def _record_intake(
        self, tenant_id: str, cycle_id: str, window_ms: int, now_ms: int
    ) -> None:
        try:
            await self._redis.record_intake(tenant_id, cycle_id, window_ms, now_ms)
        except Exception as e:
            logger.warning(f"track intake stamp failed for {cycle_id}: {e}")

    async def _count_invalid(
        self, tenant_id: str, metric_id: str, decisions: list[Decision]
    ) -> None:
        invalid = {OutcomeDisposition.INVALID: 1}
        try:
            await self._redis.count_metric_outcomes(tenant_id, metric_id, invalid)
            for cycle_id in {d.cycle_id for d in decisions}:
                await self._redis.count_outcomes(tenant_id, cycle_id, invalid)
        except Exception as e:
            logger.warning(f"invalid track count failed for {metric_id}: {e}")

    async def _count_unattributed(self, tenant_id: str, metric_id: str) -> None:
        try:
            await self._redis.count_metric_outcomes(
                tenant_id, metric_id, {OutcomeDisposition.UNATTRIBUTED: 1}
            )
        except Exception as e:
            logger.warning(f"unattributed track count failed for {metric_id}: {e}")

    async def _count_invalid_tokens(self, tenant_id: str, count: int) -> None:
        try:
            for _ in range(count):
                await self._redis.count_invalid_outcome(tenant_id)
        except Exception as e:
            logger.warning(f"invalid decisions count failed for {tenant_id}: {e}")
