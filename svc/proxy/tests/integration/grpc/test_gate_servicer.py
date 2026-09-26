"""grpc integration tests for gate servicer.

exercises the full wired stack (ProxyGRPCServicer → ProxyService → postgres/redis)
against the exact converter code that crashed live with AttributeError.
"""

from __future__ import annotations

import json

import pytest

from qbrixproto import proxy_pb2
from unittest.mock import MagicMock

import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Pool
from qbrixstore.postgres.models import Arm
from qbrixstore.postgres.models import Experiment

from proxysvc.transport.grpc.exception.base import ExperimentNotFoundException
from proxysvc.transport.grpc.exception.base import GateConfigNotFoundException

# ── helpers ───────────────────────────────────────────────────────────────────


async def _insert_pool_and_experiment(tenant_id: str) -> tuple[str, str]:
    """insert a pool + experiment directly via ORM and return (pool_id, exp_id)."""
    async with _session_module.get_session() as session:
        pool = Pool(name="grpc-test-pool", tenant_id=tenant_id)
        arm0 = Arm(name="control", index=0)
        arm1 = Arm(name="variant", index=1)
        pool.arms.append(arm0)
        pool.arms.append(arm1)
        session.add(pool)
        await session.flush()

        exp = Experiment(
            name="grpc-test-exp",
            tenant_id=tenant_id,
            pool_id=pool.id,
            policy="RandomPolicy",
            policy_params={},
            enabled=True,
        )
        session.add(exp)
        await session.flush()
        return pool.id, exp.id


def _make_gate_proto(
    rollout: float = 75.0,
    start_ms: int = 1_750_000_000_000,
    end_ms: int = 1_760_000_000_000,
) -> proxy_pb2.FeatureGateConfig:
    """build a FeatureGateConfig proto with schedule, active_hours, and a json-valued rule."""
    proto = proxy_pb2.FeatureGateConfig(
        enabled=True,
        rollout_percentage=rollout,
        timezone="UTC",
    )
    proto.schedule.start_timestamp_ms = start_ms
    proto.schedule.end_timestamp_ms = end_ms
    proto.active_hours.start = "09:00"
    proto.active_hours.end = "17:00"
    proto.rules.append(
        proxy_pb2.RuleConfig(
            key="country",
            operator="equals",
            value=json.dumps(["US", "CA"]),
            arm_id="",
        )
    )
    return proto


# ── roundtrip test ────────────────────────────────────────────────────────────


class TestCreateGetUpdateDeleteGateRoundtrip:

    async def test_roundtrip(self, wired_grpc):
        """
        full roundtrip: Create → Get → Update → Delete via gRPC servicer.
        this test would have crashed at Create before the fix with:
          AttributeError: 'dict' object has no attribute 'enabled'
        """
        ctx = MagicMock()

        _, exp_id = await _insert_pool_and_experiment("tenant-a")

        start_ms = 1_750_000_000_000
        end_ms = 1_760_000_000_000

        wired_grpc.audit_spy.events.clear()

        # ── CreateGateConfig ──────────────────────────────────────────────────
        create_req = MagicMock()
        create_req.experiment_id = exp_id
        create_req.config = _make_gate_proto(
            rollout=75.0, start_ms=start_ms, end_ms=end_ms
        )

        create_resp = await wired_grpc.servicer.CreateGateConfig(create_req, ctx)
        assert create_resp.config.enabled is True
        assert create_resp.config.rollout_percentage == 75.0
        assert create_resp.config.schedule.start_timestamp_ms == start_ms
        assert create_resp.config.schedule.end_timestamp_ms == end_ms
        assert create_resp.config.active_hours.start == "09:00"
        assert create_resp.config.active_hours.end == "17:00"
        assert create_resp.config.timezone == "UTC"
        assert len(create_resp.config.rules) == 1
        assert create_resp.config.rules[0].key == "country"
        assert create_resp.config.rules[0].value == json.dumps(["US", "CA"])

        # redis must contain the gate key
        redis_key = f"qbrix:tenant:tenant-a:gate:{exp_id}"
        raw = await wired_grpc.fake_redis.get(redis_key)
        assert raw is not None, f"gate key {redis_key!r} must be in redis after create"

        # audit event for gate creation (fire-and-forget; drain before asserting)
        await wired_grpc.events.drain()
        gate_created = [
            e for e in wired_grpc.audit_spy.events if e.name == "gate.created"
        ]
        assert len(gate_created) == 1
        assert gate_created[0].resource_id == exp_id

        # ── GetGateConfig ─────────────────────────────────────────────────────
        get_req = MagicMock()
        get_req.experiment_id = exp_id

        get_resp = await wired_grpc.servicer.GetGateConfig(get_req, ctx)
        assert get_resp.config.rollout_percentage == 75.0
        assert get_resp.config.schedule.start_timestamp_ms == start_ms
        assert get_resp.config.active_hours.start == "09:00"

        # ── UpdateGateConfig ──────────────────────────────────────────────────
        update_req = MagicMock()
        update_req.experiment_id = exp_id
        update_req.config = _make_gate_proto(
            rollout=90.0, start_ms=start_ms, end_ms=end_ms
        )
        update_req.update_mask = []

        update_resp = await wired_grpc.servicer.UpdateGateConfig(update_req, ctx)
        assert update_resp.config.rollout_percentage == 90.0
        assert update_resp.config.active_hours.start == "09:00"

        # audit event for gate update
        await wired_grpc.events.drain()
        gate_updated = [
            e for e in wired_grpc.audit_spy.events if e.name == "gate.updated"
        ]
        assert len(gate_updated) == 1
        assert gate_updated[0].resource_id == exp_id

        # ── DeleteGateConfig ──────────────────────────────────────────────────
        delete_req = MagicMock()
        delete_req.experiment_id = exp_id

        delete_resp = await wired_grpc.servicer.DeleteGateConfig(delete_req, ctx)
        assert delete_resp.deleted is True

        # audit event for gate deletion
        await wired_grpc.events.drain()
        gate_deleted = [
            e for e in wired_grpc.audit_spy.events if e.name == "gate.deleted"
        ]
        assert len(gate_deleted) == 1
        assert gate_deleted[0].resource_id == exp_id

        # subsequent GetGateConfig must raise GateConfigNotFoundException
        with pytest.raises(GateConfigNotFoundException):
            await wired_grpc.servicer.GetGateConfig(get_req, ctx)


class TestCreateGateForMissingExperiment:

    async def test_raises_for_missing_experiment(self, wired_grpc):
        """creating a gate for a non-existent experiment must raise an error.

        with postgres: FK constraint → IntegrityError → gRPC INTERNAL.
        with sqlite (fk enforced): same IntegrityError path.
        the servicer propagates the error (not silently succeeds).
        """
        from sqlalchemy.exc import IntegrityError

        ctx = MagicMock()
        req = MagicMock()
        req.experiment_id = "non-existent-exp-id"
        req.config = _make_gate_proto()

        with pytest.raises((ExperimentNotFoundException, IntegrityError, Exception)):
            await wired_grpc.servicer.CreateGateConfig(req, ctx)
