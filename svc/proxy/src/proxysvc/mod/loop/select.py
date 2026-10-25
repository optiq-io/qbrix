from __future__ import annotations

import time
import uuid
from typing import Any

from qbrixlog import get_logger
from qbrixstore.event import SelectionEvent
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
from proxysvc.mod.loop.route import LoopRoute
from proxysvc.mod.loop.route import LoopRouteCache
from proxysvc.mod.loop.route import RouteOption
from proxysvc.mod.loop.token import Decision
from proxysvc.mod.loop.token import DecisionToken
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
    option: RouteOption, request_id: str | None, reason: LoopSelectReason
) -> dict:
    return {
        "option": {"key": option.key, "name": option.name, "config": option.config},
        "request_id": request_id,
        "reason": reason.value,
    }


class LoopSelectService:
    """select(loop, context): the fallback for a draft or paused loop, the
    engine's choice from the current cycle for a live one.

    only a live answer is a decision: it carries a request_id, enters the
    ledger and counts as a selection. every answer is counted by its reason,
    and a live loop's calls by outcome per cycle, off the request path.
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
    ) -> dict:
        properties = _check_context(unit, properties)
        route = await self._routes.get(tenant_id, loop)
        if route is None:
            raise LoopNotFoundError(f"no loop with the key or id {loop!r}")

        if route.state != "live":
            reason = LoopSelectReason(route.state)
            self._count_reason(tenant_id, route.id, reason)
            return _answer(route.fallback, None, reason)

        try:
            answer = await self._decide(tenant_id, route, unit, properties)
        except Exception as e:
            self._count_outcome(tenant_id, route.cycle.id, *_classify(e))
            raise
        self._count_outcome(tenant_id, route.cycle.id, SelectOutcome.OK)
        self._count_reason(tenant_id, route.id, LoopSelectReason.LIVE)
        return answer

    async def _decide(
        self, tenant_id: str, route: LoopRoute, unit: str, properties: dict
    ) -> dict:
        await self._entitlements.on_selection(tenant_id)
        cycle_id = route.cycle.id
        choice = await self._motor_client.select(tenant_id, cycle_id, unit, [], {})
        index = choice["arm"]["index"]
        option = route.options[index]
        now_ms = int(time.time() * 1000)
        decision = Decision(
            decision_id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            loop_id=route.id,
            cycle_id=cycle_id,
            option_index=index,
            unit=unit,
            metric_version=route.metric.version,
            timestamp_ms=now_ms,
        )
        request_id = DecisionToken.encode(self._settings.token_secret_bytes, decision)
        metric = route.metric
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
                context_vector=[],
                context_metadata={},
                timestamp_ms=now_ms,
                policy=choice["policy"],
                loop_id=route.id,
                cycle_id=cycle_id,
                decision_id=decision.decision_id,
                reason=LoopSelectReason.LIVE.value,
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
        return _answer(option, request_id, LoopSelectReason.LIVE)

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
    ) -> None:
        self._events.dispatch(
            self._record_outcome(tenant_id, cycle_id, outcome, reason)
        )

    async def _record_reason(
        self, tenant_id: str, loop_id: str, reason: LoopSelectReason
    ) -> None:
        try:
            await self._redis.record_loop_select(tenant_id, loop_id, reason)
        except Exception as e:
            logger.warning(f"loop select count failed for {loop_id}: {e}")

    async def _record_outcome(
        self,
        tenant_id: str,
        cycle_id: str,
        outcome: SelectOutcome,
        reason: SelectErrorReason | None,
    ) -> None:
        try:
            await self._redis.record_select(tenant_id, cycle_id, outcome, reason)
        except Exception as e:
            logger.warning(f"select health count failed for {cycle_id}: {e}")
