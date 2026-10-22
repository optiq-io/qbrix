"""grpc integration tests for the change record.

every write over grpc records the member the interceptor authenticated, with
the api key and request id it resolved, never an empty actor.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from qbrixproto import common_pb2
from qbrixproto import proxy_pb2

from proxysvc.transport.grpc.auth.context import GRPCAuthContext
from proxysvc.transport.grpc.auth.context import set_grpc_auth_context
from proxysvc.transport.grpc.exception.base import InvalidArgumentException

TENANT = "tenant-a"


async def _create_pool(wired_grpc) -> str:
    request = proxy_pb2.CreatePoolRequest(
        name="grpc-change-pool",
        arms=[common_pb2.Arm(name="control"), common_pb2.Arm(name="variant")],
    )
    response = await wired_grpc.servicer.CreatePool(request, MagicMock())
    return response.pool.id


async def _create_experiment(wired_grpc, pool_id: str) -> str:
    request = proxy_pb2.CreateExperimentRequest(
        name="grpc-change-exp", pool_id=pool_id, policy="BetaTSPolicy", enabled=True
    )
    response = await wired_grpc.servicer.CreateExperiment(request, MagicMock())
    return response.experiment.id


class TestGrpcChanges:
    async def test_writes_record_the_authenticated_member(self, wired_grpc):
        pool_id = await _create_pool(wired_grpc)
        exp_id = await _create_experiment(wired_grpc, pool_id)

        await wired_grpc.servicer.UpdateExperiment(
            proxy_pb2.UpdateExperimentRequest(experiment_id=exp_id, enabled=False),
            MagicMock(),
        )
        await wired_grpc.servicer.DeleteExperiment(
            proxy_pb2.DeleteExperimentRequest(experiment_id=exp_id), MagicMock()
        )

        (pool_change,) = await wired_grpc.svc.list_changes(TENANT, "pool", pool_id)
        exp_changes = await wired_grpc.svc.list_changes(TENANT, "experiment", exp_id)

        assert pool_change["kind"] == "pool.create"
        assert [c["kind"] for c in exp_changes] == [
            "experiment.delete",
            "experiment.update",
            "experiment.create",
        ]
        for change in (pool_change, *exp_changes):
            assert change["actor"]["kind"] == "member"
            assert change["actor"]["user_id"] == "user-x"

    async def test_the_api_key_and_request_id_reach_the_change(self, wired_grpc):
        set_grpc_auth_context(
            GRPCAuthContext(
                tenant_id=TENANT,
                user_id="user-x",
                role="admin",
                scopes=["system:admin"],
                api_key_id="key-7",
                request_id="req-grpc-1",
            )
        )

        pool_id = await _create_pool(wired_grpc)

        (change,) = await wired_grpc.svc.list_changes(TENANT, "pool", pool_id)
        assert change["actor"]["api_key_id"] == "key-7"
        assert change["request_id"] == "req-grpc-1"


class TestUpdateExperimentGate:
    async def test_a_gate_on_update_experiment_is_refused_not_dropped(self, wired_grpc):
        pool_id = await _create_pool(wired_grpc)
        exp_id = await _create_experiment(wired_grpc, pool_id)

        request = proxy_pb2.UpdateExperimentRequest(
            experiment_id=exp_id,
            enabled=False,
            feature_gate=proxy_pb2.FeatureGateConfig(enabled=True),
        )
        with pytest.raises(InvalidArgumentException, match="UpdateGateConfig"):
            await wired_grpc.servicer.UpdateExperiment(request, MagicMock())

        kinds = [
            c["kind"]
            for c in await wired_grpc.svc.list_changes(TENANT, "experiment", exp_id)
        ]
        assert kinds == ["experiment.create"]
