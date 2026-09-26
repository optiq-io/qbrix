"""unit tests for ProxyGRPCServicer."""

from __future__ import annotations

import json
from datetime import datetime
from datetime import time
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from qbrixproto import proxy_pb2

from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.model.base import ArmConfig
from proxysvc.mod.gate.model.base import BaseArmModel
from proxysvc.mod.gate import ActiveHoursConfig
from proxysvc.mod.gate import ActivePeriodConfig
from proxysvc.mod.gate import ExperimentConfig
from proxysvc.mod.gate import RolloutConfig
from proxysvc.mod.gate import ScheduleConfig
from proxysvc.mod.gate.model.rule import Rule
from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.transport.grpc.auth.context import GRPCAuthContext
from proxysvc.transport.grpc.auth.context import set_grpc_auth_context
from proxysvc.core.error import PoolHasExperimentsError
from proxysvc.transport.grpc.exception.base import (
    ExperimentNotFoundException,
    InvalidArgumentException,
    PoolNotFoundException,
    UnauthenticatedException,
)
from proxysvc.server import ProxyGRPCServicer

# ── shared test data ──────────────────────────────────────────────────────────


POOL_DICT = {
    "id": "p-1",
    "name": "pool",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-02T00:00:00",
    "arms": [
        {
            "id": "a-1",
            "name": "arm-0",
            "index": 0,
            "is_active": True,
            "metadata": {"color": "red"},
        },
        {
            "id": "a-2",
            "name": "arm-1",
            "index": 1,
            "is_active": False,
            "metadata": {},
        },
    ],
}

# schedule timestamps used in GATE_CONFIG
_SCHEDULE_START = datetime(2025, 6, 1, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
_SCHEDULE_END = datetime(2025, 12, 31, 23, 59, 0, tzinfo=ZoneInfo("UTC"))
_EXPECTED_START_MS = int(_SCHEDULE_START.timestamp() * 1000)
_EXPECTED_END_MS = int(_SCHEDULE_END.timestamp() * 1000)

# real FeatureGateConfig with non-default values — matches what repository.to_config returns
GATE_CONFIG = FeatureGateConfig(
    experiment=ExperimentConfig(
        experiment_id="e-1",
        enabled=True,
        arm=ArmConfig(committed=BaseArmModel(id="a-1", name="arm-0")),
        rollout=RolloutConfig(percentage=80.0),
        schedule=ScheduleConfig(
            hour=ActiveHoursConfig(
                start=time(9, 0),
                end=time(17, 0),
                timezone=ZoneInfo("UTC"),
            ),
            period=ActivePeriodConfig(
                start=_SCHEDULE_START,
                end=_SCHEDULE_END,
                timezone=ZoneInfo("UTC"),
            ),
        ),
    ),
    rules=[
        Rule(
            key="country",
            operator="equals",
            value=["US", "CA"],
            arm=ArmConfig(committed=BaseArmModel(id="a-1", name="arm-0")),
        )
    ],
    version=1,
)

EXPERIMENT_DICT = {
    "id": "e-1",
    "name": "exp",
    "pool_id": "p-1",
    "policy": "BetaTSPolicy",
    "policy_params": {"alpha": 1, "beta": 1},
    "enabled": True,
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-02T00:00:00",
    "pool": POOL_DICT,
    "feature_gate": None,
}

EXPERIMENT_WITH_GATE_DICT = {
    **EXPERIMENT_DICT,
    "feature_gate": GATE_CONFIG,
}


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_service():
    """create a mock ProxyService."""
    svc = AsyncMock()
    svc.create_pool = AsyncMock(return_value=POOL_DICT)
    svc.get_pool = AsyncMock(return_value=POOL_DICT)
    svc.list_pools = AsyncMock(return_value=[POOL_DICT])
    svc.update_pool = AsyncMock(return_value={**POOL_DICT, "name": "updated-pool"})
    svc.delete_pool = AsyncMock(return_value=True)
    svc.create_experiment = AsyncMock(return_value=EXPERIMENT_DICT)
    svc.get_experiment = AsyncMock(return_value=EXPERIMENT_DICT)
    svc.update_experiment = AsyncMock(return_value=EXPERIMENT_DICT)
    svc.list_experiments = AsyncMock(return_value=[EXPERIMENT_DICT])
    svc.list_pool_experiments = AsyncMock(return_value=[EXPERIMENT_DICT])
    svc.delete_experiment = AsyncMock(return_value=True)
    svc.create_gate_config = AsyncMock(return_value=GATE_CONFIG)
    svc.get_gate_config = AsyncMock(return_value=GATE_CONFIG)
    svc.update_gate_config = AsyncMock(return_value=GATE_CONFIG)
    svc.patch_gate_config = AsyncMock(return_value=GATE_CONFIG)
    svc.delete_gate_config = AsyncMock(return_value=True)
    svc.select = AsyncMock(
        return_value={
            "arm": {"id": "a-1", "name": "arm-0", "index": 0},
            "request_id": "token",
            "is_default": False,
        }
    )
    svc.feed = AsyncMock(return_value=True)
    svc.health = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def servicer(mock_service):
    return ProxyGRPCServicer(mock_service)


@pytest.fixture
def grpc_context():
    ctx = MagicMock()
    ctx.abort = AsyncMock()
    return ctx


@pytest.fixture(autouse=True)
def set_auth_context():
    """set a default auth context for all tests and cleanup after."""
    ctx = GRPCAuthContext(
        tenant_id="test-tenant",
        user_id="test-user",
        role="admin",
        scopes=["system:admin"],
    )
    set_grpc_auth_context(ctx)
    yield
    set_grpc_auth_context(None)


# ── pool tests ────────────────────────────────────────────────────────────────


class TestGetTenantId:
    """test _get_tenant_id helper."""

    def test_returns_tenant_id(self):
        tenant_id = ProxyGRPCServicer._get_tenant_id()
        assert tenant_id == "test-tenant"

    def test_raises_when_no_context(self):
        set_grpc_auth_context(None)
        with pytest.raises(UnauthenticatedException):
            ProxyGRPCServicer._get_tenant_id()


class TestCreatePool:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.name = "my-pool"
        request.arms = []

        await servicer.CreatePool(request, grpc_context)
        mock_service.create_pool.assert_awaited_once_with("test-tenant", "my-pool", [])

    async def test_no_auth_raises(self, servicer, mock_service, grpc_context):
        set_grpc_auth_context(None)
        request = MagicMock()
        request.name = "my-pool"
        request.arms = []

        with pytest.raises(UnauthenticatedException):
            await servicer.CreatePool(request, grpc_context)
        mock_service.create_pool.assert_not_awaited()

    async def test_pool_has_timestamps_and_arm_fields(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.name = "my-pool"
        request.arms = []

        result = await servicer.CreatePool(request, grpc_context)
        assert result.pool.created_at == "2024-01-01T00:00:00"
        assert result.pool.updated_at == "2024-01-02T00:00:00"
        assert len(result.pool.arms) == 2
        assert result.pool.arms[0].is_active is True
        assert result.pool.arms[0].metadata["color"] == "red"
        assert result.pool.arms[1].is_active is False


class TestGetPool:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.pool_id = "p-1"

        await servicer.GetPool(request, grpc_context)
        mock_service.get_pool.assert_awaited_once_with("test-tenant", "p-1")

    async def test_not_found_raises(self, servicer, mock_service, grpc_context):
        mock_service.get_pool = AsyncMock(return_value=None)
        request = MagicMock()
        request.pool_id = "p-missing"

        with pytest.raises(PoolNotFoundException):
            await servicer.GetPool(request, grpc_context)


class TestListPools:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.limit = 50
        request.offset = 10

        await servicer.ListPools(request, grpc_context)
        mock_service.list_pools.assert_awaited_once_with(
            "test-tenant", limit=50, offset=10
        )

    async def test_default_limit_offset(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.limit = 0
        request.offset = 0

        await servicer.ListPools(request, grpc_context)
        mock_service.list_pools.assert_awaited_once_with(
            "test-tenant", limit=100, offset=0
        )

    async def test_no_auth_raises(self, servicer, mock_service, grpc_context):
        set_grpc_auth_context(None)
        request = MagicMock()
        request.limit = 0
        request.offset = 0

        with pytest.raises(UnauthenticatedException):
            await servicer.ListPools(request, grpc_context)
        mock_service.list_pools.assert_not_awaited()


class TestUpdatePool:

    async def test_passes_tenant_id_and_name(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.pool_id = "p-1"
        request.name = "new-name"
        request.HasField = MagicMock(return_value=True)

        await servicer.UpdatePool(request, grpc_context)
        mock_service.update_pool.assert_awaited_once_with(
            "test-tenant", "p-1", name="new-name"
        )

    async def test_not_found_raises(self, servicer, mock_service, grpc_context):
        mock_service.update_pool = AsyncMock(return_value=None)
        request = MagicMock()
        request.pool_id = "p-missing"
        request.HasField = MagicMock(return_value=False)

        with pytest.raises(PoolNotFoundException):
            await servicer.UpdatePool(request, grpc_context)

    async def test_no_auth_raises(self, servicer, mock_service, grpc_context):
        set_grpc_auth_context(None)
        request = MagicMock()
        request.pool_id = "p-1"

        with pytest.raises(UnauthenticatedException):
            await servicer.UpdatePool(request, grpc_context)
        mock_service.update_pool.assert_not_awaited()


class TestDeletePool:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.pool_id = "p-1"

        await servicer.DeletePool(request, grpc_context)
        mock_service.delete_pool.assert_awaited_once_with("test-tenant", "p-1")

    async def test_pool_has_experiments_raises(
        self, servicer, mock_service, grpc_context
    ):
        mock_service.delete_pool = AsyncMock(
            side_effect=PoolHasExperimentsError(
                "cannot delete pool: it is used by 1 experiment(s)"
            )
        )
        request = MagicMock()
        request.pool_id = "p-1"

        # PoolHasExperimentsError is a BaseAPIError — the interceptor would catch it,
        # but in unit tests we assert the raw domain error propagates from the servicer.
        with pytest.raises(PoolHasExperimentsError):
            await servicer.DeletePool(request, grpc_context)

    async def test_not_found_raises(self, servicer, mock_service, grpc_context):
        mock_service.delete_pool = AsyncMock(return_value=False)
        request = MagicMock()
        request.pool_id = "p-missing"

        with pytest.raises(PoolNotFoundException):
            await servicer.DeletePool(request, grpc_context)


# ── experiment tests ──────────────────────────────────────────────────────────


class TestCreateExperiment:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.name = "exp-1"
        request.pool_id = "p-1"
        request.policy = "BetaTSPolicy"
        request.policy_params = {}
        request.enabled = True
        request.HasField = MagicMock(return_value=False)

        await servicer.CreateExperiment(request, grpc_context)
        mock_service.create_experiment.assert_awaited_once()
        call_kwargs = mock_service.create_experiment.call_args
        assert call_kwargs.kwargs["tenant_id"] == "test-tenant"

    async def test_response_includes_pool(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.name = "exp-1"
        request.pool_id = "p-1"
        request.policy = "BetaTSPolicy"
        request.policy_params = {}
        request.enabled = True
        request.HasField = MagicMock(return_value=False)

        result = await servicer.CreateExperiment(request, grpc_context)
        assert result.pool.id == "p-1"
        assert result.pool.name == "pool"
        assert len(result.pool.arms) == 2

    async def test_response_includes_feature_gate(
        self, servicer, mock_service, grpc_context
    ):
        mock_service.create_experiment = AsyncMock(
            return_value=EXPERIMENT_WITH_GATE_DICT
        )

        request = MagicMock()
        request.name = "exp-1"
        request.pool_id = "p-1"
        request.policy = "BetaTSPolicy"
        request.policy_params = {}
        request.enabled = True
        request.HasField = MagicMock(return_value=False)

        result = await servicer.CreateExperiment(request, grpc_context)
        assert result.feature_gate.enabled is True
        assert result.feature_gate.rollout_percentage == 80.0

    async def test_experiment_has_timestamps(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.name = "exp-1"
        request.pool_id = "p-1"
        request.policy = "BetaTSPolicy"
        request.policy_params = {}
        request.enabled = True
        request.HasField = MagicMock(return_value=False)

        result = await servicer.CreateExperiment(request, grpc_context)
        assert result.experiment.created_at == "2024-01-01T00:00:00"
        assert result.experiment.updated_at == "2024-01-02T00:00:00"

    async def test_experiment_has_policy_params_json(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.name = "exp-1"
        request.pool_id = "p-1"
        request.policy = "BetaTSPolicy"
        request.policy_params = {}
        request.enabled = True
        request.HasField = MagicMock(return_value=False)

        result = await servicer.CreateExperiment(request, grpc_context)
        fields = dict(result.experiment.policy_params_json.fields)
        assert "alpha" in fields
        assert "beta" in fields


CONTEXT_SCHEMA = [
    {"name": "device", "type": "categorical", "values": ["mobile", "desktop"]},
    {"name": "cart_value", "type": "numeric", "min": 0, "max": 500},
]


class TestRequestPolicyParams:
    """real proto messages, not mocks — the encoding is what is under test."""

    async def test_struct_carries_a_context_schema_intact(
        self, servicer, mock_service, grpc_context
    ):
        """the reproduction: over the string map this arrived as a repr."""
        request = proxy_pb2.CreateExperimentRequest(
            name="ctx-exp", pool_id="p-1", policy="LinUCBPolicy", enabled=True
        )
        request.policy_params_json.update(
            {"alpha": 1.5, "context_schema": CONTEXT_SCHEMA}
        )

        await servicer.CreateExperiment(request, grpc_context)

        sent = mock_service.create_experiment.call_args.kwargs["policy_params"]
        assert isinstance(sent["context_schema"], list)
        assert sent["context_schema"] == CONTEXT_SCHEMA

    async def test_integers_survive_structs_single_number_type(
        self, servicer, mock_service, grpc_context
    ):
        """Struct stores doubles; dim must not reach the service as 4.0."""
        request = proxy_pb2.CreateExperimentRequest(
            name="dim-exp", pool_id="p-1", policy="LinUCBPolicy", enabled=True
        )
        request.policy_params_json.update({"dim": 4, "alpha": 1.5})

        await servicer.CreateExperiment(request, grpc_context)

        sent = mock_service.create_experiment.call_args.kwargs["policy_params"]
        assert sent["dim"] == 4
        assert isinstance(sent["dim"], int)
        assert sent["alpha"] == 1.5

    async def test_string_map_still_works_for_an_older_client(
        self, servicer, mock_service, grpc_context
    ):
        request = proxy_pb2.CreateExperimentRequest(
            name="legacy-exp", pool_id="p-1", policy="BetaTSPolicy", enabled=True
        )
        request.policy_params["alpha_prior"] = "1.0"

        await servicer.CreateExperiment(request, grpc_context)

        sent = mock_service.create_experiment.call_args.kwargs["policy_params"]
        assert sent == {"alpha_prior": "1.0"}

    async def test_struct_wins_when_both_are_set(
        self, servicer, mock_service, grpc_context
    ):
        request = proxy_pb2.CreateExperimentRequest(
            name="both-exp", pool_id="p-1", policy="LinUCBPolicy", enabled=True
        )
        request.policy_params["dim"] = "99"
        request.policy_params_json.update({"dim": 4})

        await servicer.CreateExperiment(request, grpc_context)

        sent = mock_service.create_experiment.call_args.kwargs["policy_params"]
        assert sent == {"dim": 4}

    async def test_update_carries_the_struct(
        self, servicer, mock_service, grpc_context
    ):
        request = proxy_pb2.UpdateExperimentRequest(experiment_id="e-1")
        request.policy_params_json.update({"alpha": 2.5, "dim": 4})

        await servicer.UpdateExperiment(request, grpc_context)

        sent = mock_service.update_experiment.call_args.kwargs["policy_params"]
        assert sent == {"alpha": 2.5, "dim": 4}

    async def test_update_without_policy_params_sends_none(
        self, servicer, mock_service, grpc_context
    ):
        """neither field set is 'not supplied', not 'replace with empty'."""
        request = proxy_pb2.UpdateExperimentRequest(experiment_id="e-1")
        request.enabled = False

        await servicer.UpdateExperiment(request, grpc_context)

        assert "policy_params" not in mock_service.update_experiment.call_args.kwargs


class TestGetExperiment:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"

        await servicer.GetExperiment(request, grpc_context)
        mock_service.get_experiment.assert_awaited_once_with("test-tenant", "e-1")

    async def test_response_includes_pool(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"

        result = await servicer.GetExperiment(request, grpc_context)
        assert result.pool.id == "p-1"
        assert len(result.pool.arms) == 2

    async def test_response_includes_feature_gate(
        self, servicer, mock_service, grpc_context
    ):
        mock_service.get_experiment = AsyncMock(return_value=EXPERIMENT_WITH_GATE_DICT)

        request = MagicMock()
        request.experiment_id = "e-1"

        result = await servicer.GetExperiment(request, grpc_context)
        assert result.feature_gate.enabled is True
        # would have silently returned 100.0 (default) before the fix
        assert result.feature_gate.rollout_percentage == 80.0

    async def test_not_found_raises(self, servicer, mock_service, grpc_context):
        mock_service.get_experiment = AsyncMock(return_value=None)
        request = MagicMock()
        request.experiment_id = "e-missing"

        with pytest.raises(ExperimentNotFoundException):
            await servicer.GetExperiment(request, grpc_context)


class TestListExperiments:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.limit = 25
        request.offset = 5
        request.HasField = MagicMock(return_value=False)

        await servicer.ListExperiments(request, grpc_context)
        mock_service.list_experiments.assert_awaited_once_with(
            "test-tenant", limit=25, offset=5
        )

    async def test_default_limit_offset(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.limit = 0
        request.offset = 0
        request.HasField = MagicMock(return_value=False)

        await servicer.ListExperiments(request, grpc_context)
        mock_service.list_experiments.assert_awaited_once_with(
            "test-tenant", limit=100, offset=0
        )

    async def test_no_auth_raises(self, servicer, mock_service, grpc_context):
        set_grpc_auth_context(None)
        request = MagicMock()
        request.limit = 0
        request.offset = 0

        with pytest.raises(UnauthenticatedException):
            await servicer.ListExperiments(request, grpc_context)
        mock_service.list_experiments.assert_not_awaited()

    async def test_passes_search_filter(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.limit = 0
        request.offset = 0

        def has_field(name):
            return name == "search"

        request.HasField = MagicMock(side_effect=has_field)
        request.search = "my-exp"

        await servicer.ListExperiments(request, grpc_context)
        mock_service.list_experiments.assert_awaited_once_with(
            "test-tenant", limit=100, offset=0, search="my-exp"
        )

    async def test_passes_enabled_filter(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.limit = 0
        request.offset = 0

        def has_field(name):
            return name == "enabled"

        request.HasField = MagicMock(side_effect=has_field)
        request.enabled = True

        await servicer.ListExperiments(request, grpc_context)
        mock_service.list_experiments.assert_awaited_once_with(
            "test-tenant", limit=100, offset=0, enabled=True
        )

    async def test_response_includes_items(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.limit = 0
        request.offset = 0
        request.HasField = MagicMock(return_value=False)

        result = await servicer.ListExperiments(request, grpc_context)
        assert len(result.items) == 1
        assert result.items[0].experiment.id == "e-1"
        assert result.items[0].pool.id == "p-1"

    async def test_items_include_feature_gate(
        self, servicer, mock_service, grpc_context
    ):
        mock_service.list_experiments = AsyncMock(
            return_value=[EXPERIMENT_WITH_GATE_DICT]
        )
        request = MagicMock()
        request.limit = 0
        request.offset = 0
        request.HasField = MagicMock(return_value=False)

        result = await servicer.ListExperiments(request, grpc_context)
        # would have been 100.0 (default) before the fix (silent data loss)
        assert result.items[0].feature_gate.rollout_percentage == 80.0


class TestListPoolExperiments:

    async def test_passes_tenant_id_and_pool_id(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.pool_id = "p-1"

        await servicer.ListPoolExperiments(request, grpc_context)
        mock_service.list_pool_experiments.assert_awaited_once_with(
            "test-tenant", "p-1"
        )

    async def test_no_auth_raises(self, servicer, mock_service, grpc_context):
        set_grpc_auth_context(None)
        request = MagicMock()
        request.pool_id = "p-1"

        with pytest.raises(UnauthenticatedException):
            await servicer.ListPoolExperiments(request, grpc_context)
        mock_service.list_pool_experiments.assert_not_awaited()

    async def test_response_includes_items(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.pool_id = "p-1"

        result = await servicer.ListPoolExperiments(request, grpc_context)
        assert len(result.items) == 1
        assert result.items[0].experiment.id == "e-1"


class TestUpdateExperiment:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.HasField = MagicMock(return_value=False)
        request.policy_params = {}

        await servicer.UpdateExperiment(request, grpc_context)
        mock_service.update_experiment.assert_awaited_once()
        args = mock_service.update_experiment.call_args[0]
        assert args[0] == "test-tenant"
        assert args[1] == "e-1"

    async def test_response_includes_pool(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.HasField = MagicMock(return_value=False)
        request.policy_params = {}

        result = await servicer.UpdateExperiment(request, grpc_context)
        assert result.pool.id == "p-1"

    async def test_not_found_raises(self, servicer, mock_service, grpc_context):
        mock_service.update_experiment = AsyncMock(return_value=None)
        request = MagicMock()
        request.experiment_id = "e-missing"
        request.HasField = MagicMock(return_value=False)
        request.policy_params = {}

        with pytest.raises(ExperimentNotFoundException):
            await servicer.UpdateExperiment(request, grpc_context)


class TestDeleteExperiment:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"

        await servicer.DeleteExperiment(request, grpc_context)
        mock_service.delete_experiment.assert_awaited_once_with("test-tenant", "e-1")

    async def test_not_found_raises(self, servicer, mock_service, grpc_context):
        mock_service.delete_experiment = AsyncMock(return_value=False)
        request = MagicMock()
        request.experiment_id = "e-missing"

        with pytest.raises(ExperimentNotFoundException):
            await servicer.DeleteExperiment(request, grpc_context)


# ── gate tests ────────────────────────────────────────────────────────────────


def _make_gate_proto_request() -> proxy_pb2.FeatureGateConfig:
    """build a real proto FeatureGateConfig with schedule, active_hours, and a rule."""
    proto = proxy_pb2.FeatureGateConfig(
        enabled=True,
        rollout_percentage=80.0,
        default_arm_id="a-1",
        timezone="UTC",
    )
    proto.schedule.start_timestamp_ms = _EXPECTED_START_MS
    proto.schedule.end_timestamp_ms = _EXPECTED_END_MS
    proto.active_hours.start = "09:00"
    proto.active_hours.end = "17:00"
    proto.rules.append(
        proxy_pb2.RuleConfig(
            key="country",
            operator="equals",
            value=json.dumps(["US", "CA"]),
            arm_id="a-1",
        )
    )
    return proto


class TestCreateGateConfig:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()

        await servicer.CreateGateConfig(request, grpc_context)
        mock_service.create_gate_config.assert_awaited_once()
        args = mock_service.create_gate_config.call_args[0]
        assert args[0] == "test-tenant"
        assert args[1] == "e-1"

    async def test_service_receives_gate_config_request(
        self, servicer, mock_service, grpc_context
    ):
        """_proto_to_gate_config must produce a GateConfigRequest, not a dict."""
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()

        await servicer.CreateGateConfig(request, grpc_context)
        args = mock_service.create_gate_config.call_args.args
        assert isinstance(args[2], GateConfigRequest)

    async def test_proto_to_gate_config_fields(
        self, servicer, mock_service, grpc_context
    ):
        """field-level assertions on what _proto_to_gate_config produces."""
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()

        await servicer.CreateGateConfig(request, grpc_context)
        args = mock_service.create_gate_config.call_args.args
        cfg: GateConfigRequest = args[2]

        assert cfg.enabled is True
        assert cfg.rollout_percentage == 80.0
        assert cfg.default_arm_id == "a-1"
        assert cfg.timezone == "UTC"
        # schedule_start is ISO string with timezone info
        assert cfg.schedule_start is not None
        assert (
            "+00:00" in cfg.schedule_start
            or "Z" in cfg.schedule_start
            or "00:00:00+00:00" in cfg.schedule_start
        )
        assert cfg.active_hours_start == "09:00"
        assert cfg.active_hours_end == "17:00"
        assert len(cfg.rules) == 1
        # json-encoded list must be decoded back to list
        assert cfg.rules[0].value == ["US", "CA"]
        assert cfg.rules[0].arm_id == "a-1"

    async def test_response_config_proto_fields(
        self, servicer, mock_service, grpc_context
    ):
        """_config_to_proto_gate must produce correct proto from FeatureGateConfig."""
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()

        resp = await servicer.CreateGateConfig(request, grpc_context)
        assert resp.config.rollout_percentage == 80.0
        assert resp.config.schedule.start_timestamp_ms == _EXPECTED_START_MS
        assert resp.config.active_hours.start == "09:00"
        # list value must be json-encoded in the proto
        assert resp.config.rules[0].value == json.dumps(["US", "CA"])
        assert resp.config.rules[0].arm_id == "a-1"

    async def test_not_found_raises(self, servicer, mock_service, grpc_context):
        mock_service.create_gate_config = AsyncMock(return_value=None)
        request = MagicMock()
        request.experiment_id = "e-missing"
        request.config = _make_gate_proto_request()

        with pytest.raises(ExperimentNotFoundException):
            await servicer.CreateGateConfig(request, grpc_context)


class TestGetGateConfig:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"

        await servicer.GetGateConfig(request, grpc_context)
        mock_service.get_gate_config.assert_awaited_once_with("test-tenant", "e-1")

    async def test_response_fields_match_gate_config(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.experiment_id = "e-1"

        resp = await servicer.GetGateConfig(request, grpc_context)
        assert resp.config.rollout_percentage == 80.0
        assert resp.config.schedule.start_timestamp_ms == _EXPECTED_START_MS
        assert resp.config.schedule.end_timestamp_ms == _EXPECTED_END_MS
        assert resp.config.active_hours.start == "09:00"
        assert resp.config.active_hours.end == "17:00"
        assert resp.config.timezone == "UTC"
        assert resp.config.default_arm_id == "a-1"
        assert len(resp.config.rules) == 1
        assert resp.config.rules[0].value == json.dumps(["US", "CA"])
        assert resp.config.rules[0].arm_id == "a-1"


class TestUpdateGateConfig:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()
        request.update_mask = []

        await servicer.UpdateGateConfig(request, grpc_context)
        mock_service.update_gate_config.assert_awaited_once()
        args = mock_service.update_gate_config.call_args[0]
        assert args[0] == "test-tenant"
        assert args[1] == "e-1"

    async def test_service_receives_gate_config_request(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()
        request.update_mask = []

        await servicer.UpdateGateConfig(request, grpc_context)
        args = mock_service.update_gate_config.call_args.args
        assert isinstance(args[2], GateConfigRequest)

    async def test_response_config_proto_fields(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()
        request.update_mask = []

        resp = await servicer.UpdateGateConfig(request, grpc_context)
        assert resp.config.rollout_percentage == 80.0
        assert resp.config.active_hours.start == "09:00"

    async def test_empty_mask_on_a_real_proto_replaces(
        self, servicer, mock_service, grpc_context
    ):
        request = proxy_pb2.UpdateGateConfigRequest(
            experiment_id="e-1", config=_make_gate_proto_request()
        )

        await servicer.UpdateGateConfig(request, grpc_context)
        mock_service.update_gate_config.assert_awaited_once()
        mock_service.patch_gate_config.assert_not_awaited()

    async def test_mask_routes_to_patch_with_only_masked_fields(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()
        request.update_mask = ["rollout_percentage"]

        await servicer.UpdateGateConfig(request, grpc_context)
        mock_service.update_gate_config.assert_not_awaited()
        args = mock_service.patch_gate_config.call_args.args
        assert args[0] == "test-tenant"
        assert args[1] == "e-1"
        assert args[2].changes() == {"rollout_percentage": 80.0}

    async def test_mask_can_clear_the_default_arm(
        self, servicer, mock_service, grpc_context
    ):
        config = _make_gate_proto_request()
        config.default_arm_id = ""
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = config
        request.update_mask = ["default_arm_id"]

        await servicer.UpdateGateConfig(request, grpc_context)
        assert mock_service.patch_gate_config.call_args.args[2].changes() == {
            "default_arm_id": None
        }

    async def test_unknown_mask_field_is_rejected(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.config = _make_gate_proto_request()
        request.update_mask = ["rollout_pct"]

        with pytest.raises(InvalidArgumentException):
            await servicer.UpdateGateConfig(request, grpc_context)
        mock_service.patch_gate_config.assert_not_awaited()
        mock_service.update_gate_config.assert_not_awaited()


class TestDeleteGateConfig:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"

        await servicer.DeleteGateConfig(request, grpc_context)
        mock_service.delete_gate_config.assert_awaited_once_with("test-tenant", "e-1")


# ── select / feedback / health ────────────────────────────────────────────────


class TestSelect:

    async def test_passes_tenant_id(self, servicer, mock_service, grpc_context):
        request = MagicMock()
        request.experiment_id = "e-1"
        request.context.id = "ctx-1"
        request.context.vector = [0.1, 0.2]
        request.context.metadata = {"key": "val"}

        await servicer.Select(request, grpc_context)
        mock_service.select.assert_awaited_once()
        call_kwargs = mock_service.select.call_args.kwargs
        assert call_kwargs["tenant_id"] == "test-tenant"
        assert call_kwargs["experiment_id"] == "e-1"


class TestFeedbackNoTenantNeeded:
    """feedback extracts tenant from token, no auth context needed."""

    async def test_feedback_does_not_call_get_tenant_id(
        self, servicer, mock_service, grpc_context
    ):
        request = MagicMock()
        request.request_id = "signed-token"
        request.reward = 1.0

        await servicer.Feedback(request, grpc_context)
        mock_service.feed.assert_awaited_once_with(
            request_id="signed-token", reward=1.0
        )

    async def test_missing_request_id_noops(self, servicer, mock_service, grpc_context):
        # an empty token (e.g. echoed from a paused selection) is a no-op, not
        # an error: the servicer returns accepted=False without calling feed.
        request = MagicMock()
        request.request_id = ""
        request.reward = 1.0

        response = await servicer.Feedback(request, grpc_context)
        assert response.accepted is False
        mock_service.feed.assert_not_awaited()


class TestHealthNoTenantNeeded:
    """health check requires no tenant context."""

    async def test_health_works_without_auth(
        self, servicer, mock_service, grpc_context
    ):
        set_grpc_auth_context(None)
        request = MagicMock()

        await servicer.Health(request, grpc_context)
        mock_service.health.assert_awaited_once()
