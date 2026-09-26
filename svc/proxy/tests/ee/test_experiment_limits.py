"""unit tests for active experiment limit enforcement."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from qbrixstore.config import RedisSettings

from proxysvc.core.events import EventEmitter
from proxysvc.service import ProxyService
from proxysvc.core.error import ExperimentLimitError
from proxysvc import edition


def _make_pool_record(**overrides):
    defaults = {
        "id": "pool-1",
        "name": "Test Pool",
        "created_at": datetime(2024, 1, 1),
        "updated_at": datetime(2024, 1, 1),
    }
    defaults.update(overrides)
    pool = MagicMock()
    for k, v in defaults.items():
        setattr(pool, k, v)
    arm = MagicMock()
    arm.id = "arm-1"
    arm.name = "control"
    arm.index = 0
    arm.is_active = True
    arm.metadata_ = {}
    pool.arms = [arm]
    return pool


def _make_experiment_record(**overrides):
    defaults = {
        "id": "exp-1",
        "name": "Test Experiment",
        "pool_id": "pool-1",
        "policy": "BetaTSPolicy",
        "policy_params": {},
        "enabled": True,
        "created_at": datetime(2024, 1, 1),
        "updated_at": datetime(2024, 1, 1),
        "pool": None,
        "feature_gate": None,
    }
    defaults.update(overrides)
    exp = MagicMock()
    for k, v in defaults.items():
        setattr(exp, k, v)
    return exp


@pytest_asyncio.fixture
async def service(
    proxy_settings,
    mock_redis,
    mock_motor_client,
    mock_cortex_client,
    mock_feedback_publisher,
):
    svc = ProxyService(proxy_settings)
    svc._redis = mock_redis
    svc._motor_client = mock_motor_client
    svc._cortex_client = mock_cortex_client
    events = EventEmitter(RedisSettings(), selection=True, audit=True)
    events._feedback = mock_feedback_publisher
    events._selection = None
    events._audit = AsyncMock()
    svc._events = events
    svc._gate_service = AsyncMock()
    svc._gate_service.evaluate = AsyncMock(return_value=None)
    svc._gate_service.set_config = AsyncMock()
    svc._gate_service.delete_config = AsyncMock()
    svc._gate_service.get_config = AsyncMock(return_value=None)
    svc._gate_service.invalidate = MagicMock()
    svc._entitlements = edition.entitlements(proxy_settings, mock_redis)
    svc._build_services()
    yield svc
    await events.drain()


class TestExperimentLimitsOnCreate:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_free_plan_under_limit_succeeds(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record()
        pool = _make_pool_record()
        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=2)  # under limit of 3
        mock_exp_repo.create = AsyncMock(return_value=exp)
        mock_exp_repo.get = AsyncMock(return_value=exp)
        mock_pool_repo = AsyncMock()
        mock_pool_repo.get = AsyncMock(return_value=pool)

        with (
            patch(
                "proxysvc.mod.experiment.service.ExperimentRepository",
                return_value=mock_exp_repo,
            ),
            patch(
                "proxysvc.mod.experiment.service.PoolRepository",
                return_value=mock_pool_repo,
            ),
        ):
            result = await service.create_experiment(
                tenant_id="t-1",
                name="exp",
                pool_id="pool-1",
                policy="BetaTSPolicy",
                policy_params={},
                enabled=True,
                plan_tier="free",
            )

        assert result["id"] == "exp-1"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_free_plan_at_limit_raises(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=3)  # at limit

        with patch(
            "proxysvc.mod.experiment.service.ExperimentRepository",
            return_value=mock_exp_repo,
        ):
            with pytest.raises(
                ExperimentLimitError, match="active experiment limit reached"
            ):
                await service.create_experiment(
                    tenant_id="t-1",
                    name="exp",
                    pool_id="pool-1",
                    policy="BetaTSPolicy",
                    policy_params={},
                    enabled=True,
                    plan_tier="free",
                )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("plan_tier", ["starter", "growth", "scale", "enterprise"])
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_paid_plans_unlimited(self, mock_get_session, service, plan_tier):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record()
        pool = _make_pool_record()
        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=999)
        mock_exp_repo.create = AsyncMock(return_value=exp)
        mock_exp_repo.get = AsyncMock(return_value=exp)
        mock_pool_repo = AsyncMock()
        mock_pool_repo.get = AsyncMock(return_value=pool)

        with (
            patch(
                "proxysvc.mod.experiment.service.ExperimentRepository",
                return_value=mock_exp_repo,
            ),
            patch(
                "proxysvc.mod.experiment.service.PoolRepository",
                return_value=mock_pool_repo,
            ),
        ):
            result = await service.create_experiment(
                tenant_id="t-1",
                name="exp",
                pool_id="pool-1",
                policy="BetaTSPolicy",
                policy_params={},
                enabled=True,
                plan_tier=plan_tier,
            )

        assert result["id"] == "exp-1"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_disabled_experiment_skips_limit_check(
        self, mock_get_session, service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record(enabled=False)
        pool = _make_pool_record()
        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=3)  # at limit
        mock_exp_repo.create = AsyncMock(return_value=exp)
        mock_exp_repo.get = AsyncMock(return_value=exp)
        mock_pool_repo = AsyncMock()
        mock_pool_repo.get = AsyncMock(return_value=pool)

        with (
            patch(
                "proxysvc.mod.experiment.service.ExperimentRepository",
                return_value=mock_exp_repo,
            ),
            patch(
                "proxysvc.mod.experiment.service.PoolRepository",
                return_value=mock_pool_repo,
            ),
        ):
            result = await service.create_experiment(
                tenant_id="t-1",
                name="exp",
                pool_id="pool-1",
                policy="BetaTSPolicy",
                policy_params={},
                enabled=False,
                plan_tier="free",
            )

        assert result["id"] == "exp-1"


class TestExperimentLimitsOnEnable:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_enabling_at_limit_raises(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=3)

        with patch(
            "proxysvc.mod.experiment.service.ExperimentRepository",
            return_value=mock_exp_repo,
        ):
            with pytest.raises(
                ExperimentLimitError,
                match="active experiment limit reached for free plan with 3 experiments",
            ):
                await service.update_experiment(
                    "t-1",
                    "exp-1",
                    plan_tier="free",
                    enabled=True,
                )

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_disabling_does_not_check_limit(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record(enabled=False)
        pool = _make_pool_record()
        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=3)
        mock_exp_repo.update = AsyncMock(return_value=exp)
        mock_exp_repo.get = AsyncMock(return_value=exp)
        mock_pool_repo = AsyncMock()
        mock_pool_repo.get = AsyncMock(return_value=pool)

        with (
            patch(
                "proxysvc.mod.experiment.service.ExperimentRepository",
                return_value=mock_exp_repo,
            ),
            patch(
                "proxysvc.mod.experiment.service.PoolRepository",
                return_value=mock_pool_repo,
            ),
        ):
            result = await service.update_experiment(
                "t-1",
                "exp-1",
                plan_tier="free",
                enabled=False,
            )

        assert result is not None
