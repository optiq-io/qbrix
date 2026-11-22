from __future__ import annotations

import time
import uuid
from datetime import datetime
from datetime import timezone
from typing import Any

from qbrixlog import get_logger
from qbrixstore.event import MilestoneEvent
from qbrixstore.event import SelectionEvent
from qbrixstore.event.milestone import FIRST_CALL
from qbrixstore.redis import LoopSelectReason
from qbrixstore.redis import RedisClient
from qbrixstore.redis import SelectErrorReason
from qbrixstore.redis import SelectOutcome

from proxysvc.config import ProxySettings
from proxysvc.core.entitlements import Entitlements
from proxysvc.core.error import DecisionContextError
from proxysvc.core.error import ExperimentNotFoundError
from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.events import EventEmitter
from proxysvc.mod.agent.service import classify_select_error
from proxysvc.mod.loop.delivery import Exclusion
from proxysvc.mod.loop.route import LoopRoute
from proxysvc.mod.loop.route import LoopRouteCache
from proxysvc.mod.loop.route import RouteOption
from proxysvc.mod.loop.token import Decision
from proxysvc.mod.loop.token import DecisionToken
from proxysvc.mod.metric.route import RouteMetric
from proxysvc.transport.grpc.client import MotorClient

logger = get_logger(__name__)

UNIT_MAX_LENGTH = 256


def _check_context(unit: Any, properties: Any) -> dict:
    if not isinstance(unit, str) or not unit.strip():
        raise DecisionContextError(
            "context.unit is required: the id of who or what sees the decision, "
            "stable for as long as its outcome can arrive"
        )
    if len(unit) > UNIT_MAX_LENGTH:
        raise DecisionContextError(
            f"context.unit is at most {UNIT_MAX_LENGTH} characters, got {len(unit)}"
        )
    if properties is None:
        return {}
    if not isinstance(properties, dict):
        raise DecisionContextError("context.properties must be an object")
    return properties


def _classify(error: Exception) -> tuple[SelectOutcome, SelectErrorReason | None]:
    """a live loop's cycle that motor can't find is qbrix's misconfiguration,
    never the caller's unknown id."""
    if isinstance(error, ExperimentNotFoundError):
        return SelectOutcome.ERROR, SelectErrorReason.CONFIG
    return classify_select_error(error)


def _answer(
    option: RouteOption,
    reason: LoopSelectReason,
    *,
    request_id: str | None = None,
    metric: RouteMetric | None = None,
) -> dict:
    return {
        "option": _option(option),
        "request_id": request_id,
        "reason": reason.value,
        "metric": metric.name if metric is not None else None,
        "window_seconds": metric.window_ms // 1000 if metric is not None else None,
    }


def _option(option: RouteOption) -> dict:
    return {"key": option.key, "name": option.name, "config": option.config}


def _preview(
    reason: LoopSelectReason,
    option: RouteOption | None,
    *,
    exclusion: Exclusion | None = None,
    defaults: list[str] | None = None,
) -> dict:
    return {
        "reason": reason.value,
        "option": _option(option) if option is not None else None,
        "excluded_by": exclusion.model_dump() if exclusion is not None else None,
        "defaults": defaults,
    }


_DECIDING = frozenset({"live", "committed"})


class LoopSelectService:
    """select(loop, context): the fallback for a draft or paused loop, the
    engine's choice from the current cycle for a live one, and the committed
    option for a committed one, without asking motor. a live or committed
    loop answers the fallback to a request outside its delivery.

    only a live or committed answer is a decision: it carries a request_id,
    enters the ledger and counts as a selection. every answer is counted by
    its reason, and a deciding loop's calls by outcome per cycle, off the
    request path.
    """

    def __init__(
        self,
        *,
        redis: RedisClient,
        routes: LoopRouteCache,
        motor_client: MotorClient,
        events: EventEmitter,
        settings: ProxySettings,
        entitlements: Entitlements,
    ):
        self._redis = redis
        self._routes = routes
        self._motor_client = motor_client
        self._events = events
        self._settings = settings
        self._entitlements = entitlements

    async def select(
        self,
        tenant_id: str,
        loop: str,
        unit: Any,
        properties: Any = None,
        *,
        source: str | None = None,
    ) -> dict:
        properties = _check_context(unit, properties)
        route = await self._routes.get(tenant_id, loop)
        if route is None:
            raise LoopNotFoundError(f"no loop with the key or id {loop!r}")

        reason = LoopSelectReason(route.state)
        if route.state not in _DECIDING:
            self._count_reason(tenant_id, route.id, reason)
            if reason is LoopSelectReason.DRAFT:
                self._events.dispatch(self._first_call(tenant_id, route.id, source))
            return _answer(route.fallback, reason)
        if not route.delivery.everyone and not route.delivery.decide(
            route.id, unit, properties, datetime.now(timezone.utc)
        ):
            self._count_reason(tenant_id, route.id, LoopSelectReason.OUTSIDE_DELIVERY)
            return _answer(route.fallback, LoopSelectReason.OUTSIDE_DELIVERY)

        try:
            answer = await self._decide(tenant_id, route, unit, properties, reason)
        except Exception as e:
            self._count_outcome(tenant_id, route.cycle.id, *_classify(e))
            raise
        self._count_outcome(
            tenant_id,
            route.cycle.id,
            SelectOutcome.OK,
            window_ms=route.metric.window_ms,
        )
        self._count_reason(tenant_id, route.id, reason)
        return answer

    async def preview(
        self,
        tenant_id: str,
        loop: str,
        unit: Any,
        properties: Any = None,
        *,
        now: datetime,
    ) -> dict:
        """what select would answer for this context, recording nothing: no
        decision, no count, no usage. a live loop's option is the engine's to
        choose, so it is left out; the exclusion names the part of the
        delivery a request falls outside of, and defaults the declared
        properties the engine would learn as their default."""
        properties = _check_context(unit, properties)
        route = await self._routes.get(tenant_id, loop)
        if route is None:
            raise LoopNotFoundError(f"no loop with the key or id {loop!r}")

        reason = LoopSelectReason(route.state)
        if route.state not in _DECIDING:
            return _preview(reason, route.fallback)
        exclusion = route.delivery.excluded_by(route.id, unit, properties, now)
        if exclusion is not None:
            return _preview(
                LoopSelectReason.OUTSIDE_DELIVERY, route.fallback, exclusion=exclusion
            )
        context = route.cycle.context
        defaults = (
            [
                prop.name
                for prop in context.root
                if not context.readable(prop.name, properties.get(prop.name))
            ]
            if context is not None
            else None
        )
        option = (
            route.options[route.committed]
            if reason is LoopSelectReason.COMMITTED
            else None
        )
        return _preview(reason, option, defaults=defaults)

    async def _decide(
        self,
        tenant_id: str,
        route: LoopRoute,
        unit: str,
        properties: dict,
        reason: LoopSelectReason,
    ) -> dict:
        await self._entitlements.on_selection(tenant_id)
        cycle_id = route.cycle.id
        context = route.cycle.context
        vector = context.encode_lenient(properties) if context is not None else []
        if reason is LoopSelectReason.COMMITTED:
            index = route.committed
            policy = reason.value
        else:
            choice = await self._motor_client.select(
                tenant_id, cycle_id, unit, vector, {}
            )
            index = choice["arm"]["index"]
            policy = choice["policy"]
        option = route.options[index]
        now_ms = int(time.time() * 1000)
        metric = route.metric
        decision = Decision(
            decision_id=uuid.uuid4().hex,
            loop_id=route.id,
            cycle_id=cycle_id,
            metric_id=metric.id,
            option_index=index,
            timestamp_ms=now_ms,
        )
        request_id = DecisionToken.encode(
            self._settings.token_secret_bytes, tenant_id, decision
        )
        self._events.emit_selection(
            SelectionEvent(
                tenant_id=tenant_id,
                experiment_id=cycle_id,
                request_id=request_id,
                arm_id=option.id,
                arm_name=option.key,
                arm_index=index,
                is_default=False,
                context_id=unit,
                context_vector=vector,
                context_metadata={},
                timestamp_ms=now_ms,
                policy=policy,
                loop_id=route.id,
                cycle_id=cycle_id,
                decision_id=decision.decision_id,
                reason=reason.value,
                unit=unit,
                properties=properties,
                metric_id=metric.id,
                metric_version=metric.version,
                metric_type=metric.type,
                score_lo=metric.score_lo or 0.0,
                score_hi=metric.score_hi or 0.0,
                window_ms=metric.window_ms,
            )
        )
        return _answer(option, reason, request_id=request_id, metric=metric)

    def _count_reason(
        self, tenant_id: str, loop_id: str, reason: LoopSelectReason
    ) -> None:
        self._events.dispatch(self._record_reason(tenant_id, loop_id, reason))

    def _count_outcome(
        self,
        tenant_id: str,
        cycle_id: str,
        outcome: SelectOutcome,
        reason: SelectErrorReason | None = None,
        *,
        window_ms: int | None = None,
    ) -> None:
        self._events.dispatch(
            self._record_outcome(tenant_id, cycle_id, outcome, reason, window_ms)
        )

    async def _record_reason(
        self, tenant_id: str, loop_id: str, reason: LoopSelectReason
    ) -> None:
        try:
            await self._redis.record_loop_select(tenant_id, loop_id, reason)
        except Exception as e:
            logger.warning(f"loop select count failed for {loop_id}: {e}")

    async def _first_call(
        self, tenant_id: str, loop_id: str, source: str | None
    ) -> None:
        """the first call a draft has had, as a milestone. the claim is given
        back if the event can't be published, so the next call tries again."""
        try:
            if not await self._redis.first_call_once(tenant_id, loop_id):
                return
        except Exception as e:
            logger.warning(f"first call check failed for {loop_id}: {e}")
            return
        try:
            await self._events.publish_milestone(
                MilestoneEvent(
                    event_id=f"first_call:{loop_id}",
                    kind=FIRST_CALL,
                    tenant_id=tenant_id,
                    loop_id=loop_id,
                    cycle_id="",
                    payload={"source": source},
                    at_ms=int(time.time() * 1000),
                )
            )
        except Exception as e:
            logger.warning(f"first call event failed for {loop_id}: {e}")
            await self._redis.forget_first_call(tenant_id, loop_id)

    async def _record_outcome(
        self,
        tenant_id: str,
        cycle_id: str,
        outcome: SelectOutcome,
        reason: SelectErrorReason | None,
        window_ms: int | None,
    ) -> None:
        try:
            await self._redis.record_select(
                tenant_id, cycle_id, outcome, reason, window_ms=window_ms
            )
        except Exception as e:
            logger.warning(f"select health count failed for {cycle_id}: {e}")
