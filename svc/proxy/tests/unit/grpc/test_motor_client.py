"""MotorClient against a real grpc server: the select deadline and NOT_FOUND."""

from __future__ import annotations

import asyncio
import time

import grpc
import pytest
import pytest_asyncio

from qbrixproto import common_pb2
from qbrixproto import motor_pb2
from qbrixproto import motor_pb2_grpc

from proxysvc.config import MotorClientSettings
from proxysvc.core.error import ExperimentNotFoundError
from proxysvc.transport.grpc.client import MotorClient


class _Motor(motor_pb2_grpc.MotorServiceServicer):
    async def Select(self, request, context):
        if request.experiment_id == "slow":
            await asyncio.sleep(5)
        if request.experiment_id == "missing":
            await context.abort(grpc.StatusCode.NOT_FOUND, "experiment not found")
        return motor_pb2.SelectResponse(
            arm=common_pb2.Arm(id="arm-1", name="control", index=0),
            policy="BetaTSPolicy",
        )


@pytest_asyncio.fixture
async def motor() -> MotorClient:
    server = grpc.aio.server()
    motor_pb2_grpc.add_MotorServiceServicer_to_server(_Motor(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    client = MotorClient(
        f"127.0.0.1:{port}", MotorClientSettings(select_timeout_ms=100)
    )
    await client.connect()
    yield client
    await client.close()
    await server.stop(grace=None)


async def select(client: MotorClient, experiment_id: str) -> dict:
    return await client.select(
        tenant_id="t-1",
        experiment_id=experiment_id,
        context_id="ctx-1",
        context_vector=[],
        context_metadata={},
    )


async def test_select_answers_within_the_deadline(motor):
    result = await select(motor, "exp-1")

    assert result["arm"]["id"] == "arm-1"


async def test_a_hung_motor_ends_at_the_deadline(motor):
    started = time.perf_counter()

    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await select(motor, "slow")

    assert raised.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
    assert time.perf_counter() - started < 1


async def test_not_found_becomes_a_domain_error(motor):
    with pytest.raises(ExperimentNotFoundError):
        await select(motor, "missing")
