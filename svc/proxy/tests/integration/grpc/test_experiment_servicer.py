"""grpc integration tests for experiment servicer — feature_gate data loss bug.

before the fix, _experiment_to_dict stored a flat GateConfigResponse dict
and _dict_to_gate_config tried to access it as a FeatureGateConfig Pydantic object,
silently producing a default-everything proto. gates were invisibly stripped from
GetExperiment / ListExperiments / ListPoolExperiments gRPC responses.

these tests prove the fix: experiment proto responses round-trip gate data correctly.
"""

from __future__ import annotations

import json

from qbrixproto import proxy_pb2
from unittest.mock import MagicMock

import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Pool
from qbrixstore.postgres.models import Arm
from qbrixstore.postgres.models import Experiment

# ── helpers ───────────────────────────────────────────────────────────────────


async def _insert_pool_and_experiment(
    tenant_id: str, *, pool_name: str = "test-pool", exp_name: str = "test-exp"
) -> tuple[str, str]:
    """insert a pool + experiment directly via ORM and return (pool_id, exp_id)."""
    async with _session_module.get_session() as session:
        pool = Pool(name=pool_name, tenant_id=tenant_id)
        pool.arms.append(Arm(name="control", index=0))
        pool.arms.append(Arm(name="variant", index=1))
        session.add(pool)
        await session.flush()

        exp = Experiment(
            name=exp_name,
            tenant_id=tenant_id,
            pool_id=pool.id,
            policy="RandomPolicy",
            policy_params={},
            enabled=True,
        )
        session.add(exp)
        await session.flush()
        return pool.id, exp.id


async def _create_gate_via_servicer(
    wired_grpc,
    exp_id: str,
    rollout: float = 60.0,
    start_ms: int = 1_750_000_000_000,
) -> None:
    ctx = MagicMock()
    req = MagicMock()
    req.experiment_id = exp_id
    proto = proxy_pb2.FeatureGateConfig(
        enabled=True,
        rollout_percentage=rollout,
        timezone="UTC",
    )
    proto.schedule.start_timestamp_ms = start_ms
    proto.active_hours.start = "08:00"
    proto.active_hours.end = "18:00"
    proto.rules.append(
        proxy_pb2.RuleConfig(
            key="tier",
            operator="equals",
            value=json.dumps("premium"),
            arm_id="",
        )
    )
    req.config = proto
    await wired_grpc.servicer.CreateGateConfig(req, ctx)


# ── test: GetExperiment includes gate data ────────────────────────────────────


class TestGetExperimentIncludesGate:

    async def test_get_experiment_feature_gate_fields_match(self, wired_grpc):
        """
        GetExperiment must return feature_gate with the configured values,
        not default-everything values (100% rollout, no schedule, no rules).
        """
        ctx = MagicMock()

        _, exp_id = await _insert_pool_and_experiment(
            "tenant-a", pool_name="get-pool", exp_name="get-exp"
        )
        start_ms = 1_750_000_000_000
        await _create_gate_via_servicer(
            wired_grpc, exp_id, rollout=60.0, start_ms=start_ms
        )

        req = MagicMock()
        req.experiment_id = exp_id
        resp = await wired_grpc.servicer.GetExperiment(req, ctx)

        # before the fix this would have returned rollout_percentage=100.0
        assert resp.feature_gate.enabled is True
        assert resp.feature_gate.rollout_percentage == 60.0
        assert resp.feature_gate.schedule.start_timestamp_ms == start_ms
        assert resp.feature_gate.active_hours.start == "08:00"
        assert resp.feature_gate.active_hours.end == "18:00"
        assert len(resp.feature_gate.rules) == 1
        assert resp.feature_gate.rules[0].key == "tier"


# ── test: ListExperiments includes gate data ─────────────────────────────────


class TestListExperimentsIncludesGate:

    async def test_list_experiments_items_include_feature_gate(self, wired_grpc):
        """
        ListExperiments.items[*].feature_gate must carry the configured gate.
        this exercises _build_experiment_detail (server.py:324) which was also
        affected by the silent data loss bug.
        """
        ctx = MagicMock()

        _, exp_id = await _insert_pool_and_experiment(
            "tenant-a", pool_name="list-pool", exp_name="list-exp"
        )
        start_ms = 1_750_000_000_000
        await _create_gate_via_servicer(
            wired_grpc, exp_id, rollout=55.0, start_ms=start_ms
        )

        req = MagicMock()
        req.limit = 100
        req.offset = 0
        req.HasField = MagicMock(return_value=False)
        resp = await wired_grpc.servicer.ListExperiments(req, ctx)

        # find our experiment in the items list
        items = [item for item in resp.items if item.experiment.id == exp_id]
        assert (
            len(items) == 1
        ), f"experiment {exp_id} not found in ListExperiments.items"
        gate = items[0].feature_gate

        assert gate.enabled is True
        assert gate.rollout_percentage == 55.0
        assert gate.schedule.start_timestamp_ms == start_ms

    async def test_list_pool_experiments_items_include_feature_gate(self, wired_grpc):
        """
        ListPoolExperiments.items[*].feature_gate must carry gate data.
        covers _build_experiment_detail used by ListPoolExperiments.
        """
        ctx = MagicMock()

        pool_id, exp_id = await _insert_pool_and_experiment(
            "tenant-a", pool_name="lpe-pool", exp_name="lpe-exp"
        )
        start_ms = 1_750_000_000_001
        await _create_gate_via_servicer(
            wired_grpc, exp_id, rollout=45.0, start_ms=start_ms
        )

        req = MagicMock()
        req.pool_id = pool_id
        resp = await wired_grpc.servicer.ListPoolExperiments(req, ctx)

        items = [item for item in resp.items if item.experiment.id == exp_id]
        assert len(items) == 1
        gate = items[0].feature_gate

        assert gate.rollout_percentage == 45.0
        assert gate.schedule.start_timestamp_ms == start_ms
