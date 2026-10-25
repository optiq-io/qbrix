from __future__ import annotations

import math
import time
import uuid
from datetime import datetime
from datetime import timezone
from typing import Any

from qbrixlog import get_logger
from qbrixstore.event import MetricEvent
from qbrixstore.redis import OutcomeDisposition
from qbrixstore.redis import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.error import InvalidOutcomeError
from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import TokenInvalidError
from proxysvc.core.events import EventEmitter
from proxysvc.mod.loop.route import LoopRouteCache
from proxysvc.mod.loop.route import RouteMetric
from proxysvc.mod.loop.token import Decision
from proxysvc.mod.loop.token import DecisionToken

logger = get_logger(__name__)

EVENT_ID_MAX_LENGTH = 256
MAX_CLOCK_AHEAD_MS = 5 * 60 * 1000
SOURCE = "outcome"


def _check_value(metric: RouteMetric, value: Any) -> float:
    """the value as the metric's type accepts it, or the rule it breaks."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidOutcomeError(f"value must be a number, got {value!r}")
    if not math.isfinite(value):
        raise InvalidOutcomeError(f"value must be a finite number, got {value}")
    if metric.type == "conversion":
        if value not in (0, 1):
            raise InvalidOutcomeError(f"a conversion is 0 or 1, got {value}")
    elif metric.type == "count":
        if value < 0 or value != int(value):
            raise InvalidOutcomeError(
                f"a count is a whole number of 0 or more, got {value}"
            )
    elif metric.type == "score":
        lo, hi = metric.score_lo, metric.score_hi
        if not lo <= value <= hi:
            raise InvalidOutcomeError(
                f"a score for this metric is between {lo:g} and {hi:g}, got {value}"
            )
    return float(value)


def _check_event_id(event_id: Any) -> str:
    if event_id is None:
        return uuid.uuid4().hex
    if not isinstance(event_id, str) or not event_id.strip():
        raise InvalidOutcomeError("id must be a non-empty string")
    if len(event_id) > EVENT_ID_MAX_LENGTH:
        raise InvalidOutcomeError(
            f"id is at most {EVENT_ID_MAX_LENGTH} characters, got {len(event_id)}"
        )
    return event_id


def _at_ms(at: datetime | None, decision: Decision, now_ms: int) -> int:
    if at is None:
        return now_ms
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    at_ms = int(at.timestamp() * 1000)
    if at_ms < decision.timestamp_ms:
        raise InvalidOutcomeError("at is earlier than the decision")
    if at_ms > now_ms + MAX_CLOCK_AHEAD_MS:
        raise InvalidOutcomeError("at is more than 5 minutes ahead of now")
    return at_ms


class LoopOutcomeService:
    """outcome(request_id, value): the event for exactly one decision, with its
    loop's metric.

    what is accepted is recorded, late, repeated and earlier-cycle outcomes
    included; the sealer decides what is learned. nothing here reads postgres:
    the metric comes from the loop's route.
    """

    def __init__(
        self,
        *,
        redis: RedisClient,
        routes: LoopRouteCache,
        events: EventEmitter,
        settings: ProxySettings,
    ):
        self._redis = redis
        self._routes = routes
        self._events = events
        self._settings = settings

    async def outcome(
        self,
        tenant_id: str,
        request_id: str,
        value: Any,
        event_id: Any = None,
        at: datetime | None = None,
    ) -> dict:
        try:
            decision = DecisionToken.decode(
                self._settings.token_secret_bytes, request_id, tenant_id
            )
        except TokenInvalidError:
            self._events.dispatch(self._count_invalid_token(tenant_id))
            raise

        route = await self._routes.get(tenant_id, decision.loop_id)
        if route is None:
            raise LoopNotFoundError(f"no loop with the id {decision.loop_id!r}")

        try:
            value = _check_value(route.metric, value)
        except InvalidOutcomeError:
            self._events.dispatch(self._count_invalid(tenant_id, decision.cycle_id))
            raise

        now_ms = int(time.time() * 1000)
        event_id = _check_event_id(event_id)
        at_ms = _at_ms(at, decision, now_ms)

        self._events.emit_metric(
            MetricEvent(
                tenant_id=tenant_id,
                metric_id=route.metric.id,
                metric_version=decision.metric_version,
                value=value,
                decisions=[
                    {
                        "decision_id": decision.decision_id,
                        "loop_id": decision.loop_id,
                        "cycle_id": decision.cycle_id,
                        "option_index": decision.option_index,
                        "opened_ms": decision.timestamp_ms,
                    }
                ],
                unit=decision.unit,
                event_id=event_id,
                at_ms=at_ms,
                received_ms=now_ms,
                source=SOURCE,
            )
        )
        return {"id": event_id, "at_ms": at_ms}

    async def _count_invalid(self, tenant_id: str, cycle_id: str) -> None:
        try:
            await self._redis.count_outcomes(
                tenant_id, cycle_id, {OutcomeDisposition.INVALID: 1}
            )
        except Exception as e:
            logger.warning(f"invalid outcome count failed for {cycle_id}: {e}")

    async def _count_invalid_token(self, tenant_id: str) -> None:
        try:
            await self._redis.count_invalid_outcome(tenant_id)
        except Exception as e:
            logger.warning(f"invalid outcome count failed for {tenant_id}: {e}")
