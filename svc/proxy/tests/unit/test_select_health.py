"""every select call is counted by outcome, off the request path."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import grpc
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from qbrixstore.config import RedisSettings
from qbrixstore.redis import RedisClient
from qbrixstore.redis import SelectHealth

from proxysvc.core.error import ContextPropertiesError
from proxysvc.core.error import ContextVectorError
from proxysvc.core.error import ExperimentNotFoundError
from proxysvc.core.error import UsageLimitError
from proxysvc.core.events import EventEmitter
from proxysvc.mod.agent.service import AgentService
from proxysvc.mod.experiment.cache import ExperimentState
from proxysvc.mod.gate.model.base import BaseArmModel

TENANT = "t-1"
EXPERIMENT = "exp-1"
ARM = {"id": "arm-1", "name": "first", "index": 0}


def rpc_error(code: grpc.StatusCode) -> grpc.aio.AioRpcError:
    return grpc.aio.AioRpcError(
        code, grpc.aio.Metadata(), grpc.aio.Metadata(), details=code.name
    )


@pytest_asyncio.fixture
async def redis() -> RedisClient:
    client = RedisClient()
    client._client = FakeRedis(decode_responses=True)
    yield client
    await client.close()


@pytest_asyncio.fixture
async def events() -> EventEmitter:
    emitter = EventEmitter(RedisSettings())
    emitter._feedback = AsyncMock()
    emitter._selection = AsyncMock()
    emitter._audit = AsyncMock()
    yield emitter
    await emitter.drain()


@pytest.fixture
def agent(redis, events, proxy_settings) -> AgentService:
    experiments = AsyncMock()
    experiments.get_state = AsyncMock(return_value=ExperimentState(pool={}))
    gates = AsyncMock()
    gates.evaluate = AsyncMock(return_value=None)
    gates.get_config = AsyncMock(return_value=None)
    motor = AsyncMock()
    motor.select = AsyncMock(return_value={"arm": dict(ARM), "policy": "BetaTSPolicy"})
    entitlements = AsyncMock()
    entitlements.on_selection = AsyncMock()
    return AgentService(
        redis=redis,
        gate_service=gates,
        motor_client=motor,
        events=events,
        settings=proxy_settings,
        experiment_service=experiments,
        entitlements=entitlements,
    )


async def select(agent: AgentService, **kwargs) -> dict:
    return await agent.select(
        tenant_id=TENANT,
        experiment_id=kwargs.pop("experiment_id", EXPERIMENT),
        context_id="ctx-1",
        **kwargs,
    )


async def health(agent, redis, experiment_id: str = EXPERIMENT) -> SelectHealth:
    await agent._events.drain()
    return await redis.select_health(TENANT, experiment_id, 10)


class TestAnswered:

    async def test_motor_selection_counts_ok(self, agent, redis):
        await select(agent)

        assert await health(agent, redis) == SelectHealth(ok=1)

    async def test_gate_selection_counts_ok(self, agent, redis):
        agent._gate_service.evaluate.return_value = BaseArmModel(**ARM)

        await select(agent)

        agent._motor_client.select.assert_not_awaited()
        assert await health(agent, redis) == SelectHealth(ok=1)

    async def test_paused_selection_counts_ok(self, agent, redis):
        agent._experiment_service.get_state.return_value = ExperimentState(
            enabled=False, pool={"arms": [ARM]}
        )

        await select(agent)

        assert await health(agent, redis) == SelectHealth(ok=1)

    async def test_meta_selection_counts_against_the_requested_experiment(
        self, agent, redis
    ):
        agent._motor_client.select.return_value = {
            "arm": dict(ARM),
            "policy": "BetaTSPolicy",
            "learner_experiment_id": "learner-1",
            "learner_index": 0,
        }

        await select(agent, experiment_id="meta-1")

        assert await health(agent, redis, "meta-1") == SelectHealth(ok=1)
        assert await health(agent, redis, "learner-1") == SelectHealth()


class TestClient:

    async def test_context_vector_error_counts_client(self, agent, redis):
        agent._experiment_service.get_state.return_value = ExperimentState(
            policy_params={"dim": 2}
        )

        with pytest.raises(ContextVectorError):
            await select(agent, context_vector=[1.0])

        assert await health(agent, redis) == SelectHealth(client=1)

    async def test_context_properties_error_counts_client(self, agent, redis):
        with pytest.raises(ContextPropertiesError):
            await select(agent, context_vector=[1.0], context_properties={"a": 1})

        assert await health(agent, redis) == SelectHealth(client=1)

    async def test_quota_counts_client(self, agent, redis):
        agent._entitlements.on_selection.side_effect = UsageLimitError("over quota")

        with pytest.raises(UsageLimitError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(client=1)


class TestNotFound:

    async def test_motor_not_found_counts_not_found(self, agent, redis):
        agent._motor_client.select.side_effect = ExperimentNotFoundError("exp-1")

        with pytest.raises(ExperimentNotFoundError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(not_found=1)


class TestError:

    @pytest.mark.parametrize(
        "code, reason",
        [
            (grpc.StatusCode.DEADLINE_EXCEEDED, "motor_timeout"),
            (grpc.StatusCode.UNAVAILABLE, "motor_unavailable"),
            (grpc.StatusCode.INTERNAL, "motor_internal"),
        ],
    )
    async def test_motor_failure_counts_its_reason(self, agent, redis, code, reason):
        agent._motor_client.select.side_effect = rpc_error(code)

        with pytest.raises(grpc.aio.AioRpcError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(
            error=1, by_reason={reason: 1}
        )

    async def test_cache_read_failure_counts_store(self, agent, redis):
        agent._experiment_service.get_state.side_effect = RedisConnectionError()

        with pytest.raises(RedisConnectionError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(
            error=1, by_reason={"store": 1}
        )

    async def test_corrupt_cache_record_counts_store(self, agent, redis):
        try:
            ExperimentState.model_validate_json("{")
        except ValidationError as e:
            agent._experiment_service.get_state.side_effect = e

        with pytest.raises(ValidationError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(
            error=1, by_reason={"store": 1}
        )

    async def test_quota_store_failure_counts_store(self, agent, redis):
        agent._entitlements.on_selection.side_effect = RedisConnectionError()

        with pytest.raises(RedisConnectionError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(
            error=1, by_reason={"store": 1}
        )

    async def test_paused_without_a_default_arm_counts_config(self, agent, redis):
        agent._experiment_service.get_state.return_value = ExperimentState(
            enabled=False, pool={"arms": []}
        )

        with pytest.raises(ValueError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(
            error=1, by_reason={"config": 1}
        )

    async def test_unclassified_failure_counts_internal(self, agent, redis):
        agent._motor_client.select.side_effect = RuntimeError("not connected")

        with pytest.raises(RuntimeError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(
            error=1, by_reason={"internal": 1}
        )

    async def test_gate_failure_still_answers_and_counts_gate(self, agent, redis):
        agent._gate_service.evaluate.side_effect = RedisConnectionError()

        result = await select(agent)

        assert result["arm"]["id"] == ARM["id"]
        agent._motor_client.select.assert_awaited_once()
        assert await health(agent, redis) == SelectHealth(
            error=1, by_reason={"gate": 1}
        )

    async def test_motor_failure_after_gate_failure_counts_motor(self, agent, redis):
        agent._gate_service.evaluate.side_effect = RedisConnectionError()
        agent._motor_client.select.side_effect = rpc_error(grpc.StatusCode.UNAVAILABLE)

        with pytest.raises(grpc.aio.AioRpcError):
            await select(agent)

        assert await health(agent, redis) == SelectHealth(
            error=1, by_reason={"motor_unavailable": 1}
        )


class TestOffTheHotPath:

    async def test_a_hung_counter_does_not_hold_the_selection(self, agent, events):
        never = asyncio.Event()

        async def hang(*_args, **_kwargs):
            await never.wait()

        agent._redis.record_select = hang

        started = time.perf_counter()
        result = await asyncio.wait_for(select(agent), timeout=1)

        assert result["arm"]["id"] == ARM["id"]
        assert time.perf_counter() - started < 0.1
        assert events._inflight
        for task in tuple(events._inflight):
            task.cancel()

    async def test_a_failed_count_is_dropped(self, agent, events):
        agent._redis.record_select = AsyncMock(side_effect=RedisConnectionError())

        result = await select(agent)
        await events.drain()

        assert result["arm"]["id"] == ARM["id"]
        agent._redis.record_select.assert_awaited_once()
