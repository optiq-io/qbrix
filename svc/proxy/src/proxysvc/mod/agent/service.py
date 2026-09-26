from __future__ import annotations

import time
import uuid

from qbrixlog import get_logger
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent

from qbrixcore.context_schema import ContextEncodeError

from proxysvc.config import ProxySettings
from proxysvc.core.error import ContextPropertiesError
from proxysvc.core.error import ContextVectorError
from proxysvc.core.entitlements import Entitlements
from proxysvc.core.events import EventEmitter
from proxysvc.mod.agent.token import SelectionToken
from proxysvc.mod.experiment.cache import ExperimentState
from proxysvc.mod.experiment.service import ExperimentService
from proxysvc.mod.gate import GateService
from proxysvc.transport.grpc.client import MotorClient

logger = get_logger(__name__)


def _validate_context_vector(
    state: ExperimentState, context_vector: list[float] | None
) -> None:
    """check the supplied vector against the experiment's configured dim.

    an absent vector counts as width 0, so switching an experiment to
    contextual is reported the same way as encoding it wrongly. a vector sent
    to a non-contextual experiment is left alone: those policies ignore it.
    """
    dim = state.context_dim
    if dim is None:
        return

    width = len(context_vector or [])
    if width != dim:
        raise ContextVectorError(
            f"context.vector has width {width}, experiment expects {dim}"
        )


def _resolve_context_vector(
    state: ExperimentState | None,
    context_vector: list[float] | None,
    context_properties: dict | None,
) -> list[float] | None:
    """settle on the vector the policies will see.

    a schema-backed experiment encodes named properties here, once, and the
    result is what the token carries — so feedback replays the same vector and
    nothing downstream re-encodes. the dim-only escape hatch keeps taking a
    pre-encoded vector, and still rejects an absent one: without a
    schema there is no principled default for an absent context.
    """
    if context_vector is not None and context_properties is not None:
        raise ContextPropertiesError(
            "send context.vector or context.properties, not both"
        )

    if state is None:
        return context_vector

    schema = state.context_schema
    if schema is None:
        if context_properties is not None and state.context_dim is not None:
            raise ContextPropertiesError(
                "this experiment was not created with a context schema; "
                "send context.vector"
            )
        _validate_context_vector(state, context_vector)
        return context_vector

    if context_vector is not None:
        raise ContextPropertiesError(
            "this experiment declares a context schema; send context.properties"
        )

    try:
        return schema.encode(context_properties)
    except ContextEncodeError as e:
        raise ContextPropertiesError(str(e)) from e


class AgentService:
    """selection + feedback hot path.

    short-circuits paused experiments to a control arm, otherwise evaluates the
    feature gate, routes to motorsvc for algorithmic selection, mints signed
    selection tokens, and emits ee selection/feedback events through the shared
    EventEmitter (fire-and-forget).
    """

    def __init__(
        self,
        *,
        gate_service: GateService,
        motor_client: MotorClient,
        events: EventEmitter,
        settings: ProxySettings,
        experiment_service: ExperimentService,
        entitlements: Entitlements,
    ):
        self._gate_service = gate_service
        self._motor_client = motor_client
        self._events = events
        self._settings = settings
        self._experiment_service = experiment_service
        self._entitlements = entitlements

    async def select(
        self,
        tenant_id: str,
        experiment_id: str,
        context_id: str,
        context_vector: list[float] | None = None,
        context_metadata: dict | None = None,
        context_properties: dict | None = None,
    ) -> dict:
        state = await self._experiment_service.get_state(tenant_id, experiment_id)

        # encode before metering so a malformed request is not billed, and
        # before the paused branch so pausing never changes what is accepted.
        # everything below this line sees one vector, whichever way it arrived.
        context_vector = _resolve_context_vector(
            state, context_vector, context_properties
        )

        # covers all three billable return paths below
        await self._entitlements.on_selection(tenant_id)

        if state is not None and not state.enabled:
            return await self._paused_response(
                tenant_id=tenant_id,
                experiment_id=experiment_id,
                state=state,
                context_id=context_id,
                context_vector=context_vector,
                context_metadata=context_metadata,
            )

        # evaluate feature gate first
        committed_arm = await self._gate_service.evaluate(
            tenant_id=tenant_id,
            experiment_id=experiment_id,
            context_id=context_id,
            context_metadata=context_metadata,
        )

        if committed_arm is not None and committed_arm.index is not None:
            # gate will be determined at the gate level, skips selection routing.
            token = SelectionToken.encode(
                secret=self._settings.token_secret_bytes,
                tenant_id=tenant_id,
                experiment_id=experiment_id,
                arm_index=committed_arm.index,
                context_id=context_id,
                context_vector=context_vector,
                context_metadata=context_metadata,
            )
            result = {
                "arm": {
                    "id": committed_arm.id,
                    "name": committed_arm.name,
                    "index": committed_arm.index,
                },
                "request_id": token,
                "is_default": True,
            }

            if self._events.selection_enabled:
                self._events.emit_selection(
                    SelectionEvent(
                        tenant_id=tenant_id,
                        experiment_id=experiment_id,
                        request_id=token,
                        event_id=str(uuid.uuid4()),
                        arm_id=committed_arm.id,
                        arm_name=committed_arm.name,
                        arm_index=committed_arm.index,
                        is_default=True,
                        context_id=context_id,
                        context_vector=context_vector,
                        context_metadata=context_metadata,
                        timestamp_ms=int(time.time() * 1000),
                        policy="gate",
                    )
                )

            return result

        # gate selection not valid, route to motorsvc for actual algorithmic selection.
        response = await self._motor_client.select(
            tenant_id=tenant_id,
            experiment_id=experiment_id,
            context_id=context_id,
            context_vector=context_vector,
            context_metadata=context_metadata,
        )

        # meta-bandit: encode token with learner experiment context
        learner_experiment_id = response.get("learner_experiment_id")
        if learner_experiment_id:
            token = SelectionToken.encode(
                secret=self._settings.token_secret_bytes,
                tenant_id=tenant_id,
                experiment_id=learner_experiment_id,
                arm_index=response["arm"]["index"],
                context_id=context_id,
                context_vector=context_vector,
                context_metadata=context_metadata,
                meta_experiment_id=experiment_id,
                learner_index=response["learner_index"],
                learner_experiment_id=learner_experiment_id,
            )
        else:
            token = SelectionToken.encode(
                secret=self._settings.token_secret_bytes,
                tenant_id=tenant_id,
                experiment_id=experiment_id,
                arm_index=response["arm"]["index"],
                context_id=context_id,
                context_vector=context_vector,
                context_metadata=context_metadata,
            )
        response["request_id"] = token
        response["is_default"] = False

        if self._events.selection_enabled:
            # for meta-bandit, publish selection under the learner experiment id
            # so insights queries (which resolve to learner ids) find the data
            selection_experiment_id = (
                learner_experiment_id if learner_experiment_id else experiment_id
            )
            self._events.emit_selection(
                SelectionEvent(
                    tenant_id=tenant_id,
                    experiment_id=selection_experiment_id,
                    request_id=token,
                    event_id=str(uuid.uuid4()),
                    arm_id=response["arm"]["id"],
                    arm_name=response["arm"]["name"],
                    arm_index=response["arm"]["index"],
                    is_default=False,
                    context_id=context_id,
                    context_vector=context_vector,
                    context_metadata=context_metadata,
                    timestamp_ms=int(time.time() * 1000),
                    policy=response["policy"],
                )
            )

        return response

    async def _paused_response(
        self,
        *,
        tenant_id: str,
        experiment_id: str,
        state: ExperimentState,
        context_id: str,
        context_vector: list[float],
        context_metadata: dict,
    ) -> dict:
        """build the control-arm response for a paused experiment.

        no token is minted, so the selection can never be fed back as learning.
        """
        arm = await self._control_arm(tenant_id, experiment_id, state)
        result = {"arm": arm, "request_id": None, "is_default": True}

        if self._events.selection_enabled:
            self._events.emit_selection(
                SelectionEvent(
                    tenant_id=tenant_id,
                    experiment_id=experiment_id,
                    request_id="",
                    event_id=str(uuid.uuid4()),
                    arm_id=arm["id"],
                    arm_name=arm["name"],
                    arm_index=arm["index"],
                    is_default=True,
                    context_id=context_id,
                    context_vector=context_vector,
                    context_metadata=context_metadata,
                    timestamp_ms=int(time.time() * 1000),
                    policy="paused",
                )
            )

        return result

    async def _control_arm(
        self, tenant_id: str, experiment_id: str, state: ExperimentState
    ) -> dict:
        """resolve the control arm: gate default_arm if defined, else pool arm 0."""
        config = await self._gate_service.get_config(tenant_id, experiment_id)
        if config is not None:
            committed = config.experiment.arm.committed
            if committed is not None and committed.index is not None:
                return {
                    "id": committed.id,
                    "name": committed.name,
                    "index": committed.index,
                }

        arms = state.pool.get("arms") or []
        if not arms:
            raise ValueError(
                f"paused experiment {experiment_id} has no control arm available"
            )
        arm = arms[0]
        return {"id": arm["id"], "name": arm["name"], "index": arm["index"]}

    async def feed(self, request_id: str, reward: float) -> bool:
        """
        process feedback for a prior selection.

        args:
            request_id: signed token from select() containing selection context
            reward: observed reward value

        returns:
            True if feedback was accepted; False if no token was supplied
            (e.g. a client echoing back the null token from a paused selection)

        raises:
            TokenError: if a non-empty token is invalid or expired
        """
        if not request_id:
            return False

        selection = SelectionToken.decode(
            secret=self._settings.token_secret_bytes,
            token=request_id,
            max_age_ms=self._settings.token_max_age_ms,
        )

        now_ms = int(time.time() * 1000)

        learner_event = FeedbackEvent(
            tenant_id=selection.tenant_id,
            experiment_id=selection.experiment_id,
            request_id=request_id,
            arm_index=selection.arm_index,
            reward=reward,
            context_id=selection.context_id,
            context_vector=selection.context_vector,
            context_metadata=selection.context_metadata,
            timestamp_ms=now_ms,
        )

        if (
            selection.meta_experiment_id is not None
            and selection.learner_index is not None
        ):
            # meta-bandit: publish both learner and meta training events
            meta_event = FeedbackEvent(
                tenant_id=selection.tenant_id,
                experiment_id=selection.meta_experiment_id,
                request_id=request_id,
                arm_index=selection.learner_index,
                reward=reward,
                context_id=selection.context_id,
                context_vector=selection.context_vector,
                context_metadata=selection.context_metadata,
                timestamp_ms=now_ms,
            )
            self._events.emit_feedback(learner_event, meta_event)
        else:
            self._events.emit_feedback(learner_event)

        return True
