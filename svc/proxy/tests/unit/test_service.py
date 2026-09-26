"""unit tests for ProxyService orchestrator."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from qbrixstore.config import RedisSettings

from proxysvc.core.events import EventEmitter
from proxysvc.service import ProxyService
from proxysvc.core.error import PoolHasExperimentsError
from proxysvc.core.error import ExperimentRunningError
from proxysvc.core.error import TokenInvalidError
from proxysvc.mod.agent.token import SelectionToken
from proxysvc.mod.gate.model.base import BaseArmModel
from proxysvc import edition


def _make_pool_record(**overrides):
    """create a mock Pool ORM object."""
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
    """create a mock Experiment ORM object."""
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
    """create a ProxyService with injected mocks (no start() needed)."""
    svc = ProxyService(proxy_settings)
    svc._redis = mock_redis
    svc._motor_client = mock_motor_client
    svc._cortex_client = mock_cortex_client
    # event egress: emitter with mock stream publishers. selection is disabled
    # by default (mirrors the previous _selection_publisher = None); tests that
    # exercise selection enable it by setting svc._events._selection.
    events = EventEmitter(RedisSettings(), selection=True, audit=True)
    events._feedback = mock_feedback_publisher
    events._selection = None
    events._audit = AsyncMock()
    svc._events = events
    # gate service with mocked cache
    svc._gate_service = AsyncMock()
    svc._gate_service.evaluate = AsyncMock(return_value=None)
    svc._gate_service.set_config = AsyncMock()
    svc._gate_service.delete_config = AsyncMock()
    svc._gate_service.get_config = AsyncMock(return_value=None)
    svc._gate_service.invalidate = MagicMock()
    # the selection meter is exercised in dedicated metering tests; here it is
    # a no-op so select() does not touch redis/postgres.
    svc._entitlements = edition.entitlements(proxy_settings, mock_redis)
    svc._entitlements.on_selection = AsyncMock()
    svc._build_services()
    yield svc
    await events.drain()


class TestProxyServiceSelect:

    @pytest.mark.asyncio
    async def test_gate_returns_arm_skips_motor(self, service):
        committed = BaseArmModel(name="default", id="arm-0", index=0)
        service._gate_service.evaluate = AsyncMock(return_value=committed)

        result = await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[1.0],
            context_metadata={},
        )

        assert result["is_default"] is True
        assert result["arm"]["index"] == 0
        service._motor_client.select.assert_not_called()

    @pytest.mark.asyncio
    async def test_gate_none_routes_to_motor(self, service):
        service._gate_service.evaluate = AsyncMock(return_value=None)
        service._motor_client.select = AsyncMock(
            return_value={"arm": {"id": "arm-2", "name": "variant", "index": 1}}
        )

        result = await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[1.0],
            context_metadata={},
        )

        assert result["is_default"] is False
        assert result["arm"]["index"] == 1
        service._motor_client.select.assert_called_once()

    @pytest.mark.asyncio
    async def test_gated_result_has_valid_token(self, service):
        committed = BaseArmModel(name="default", id="arm-0", index=0)
        service._gate_service.evaluate = AsyncMock(return_value=committed)

        result = await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[1.0],
            context_metadata={"k": "v"},
        )

        token = result["request_id"]
        entry = SelectionToken.decode(
            secret=service._settings.token_secret_bytes, token=token
        )
        assert entry.tenant_id == "t-1"
        assert entry.experiment_id == "exp-1"
        assert entry.arm_index == 0

    @pytest.mark.asyncio
    async def test_motor_result_has_valid_token(self, service):
        service._gate_service.evaluate = AsyncMock(return_value=None)
        service._motor_client.select = AsyncMock(
            return_value={"arm": {"id": "arm-1", "name": "control", "index": 0}}
        )

        result = await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[],
            context_metadata={},
        )

        entry = SelectionToken.decode(
            secret=service._settings.token_secret_bytes,
            token=result["request_id"],
        )
        assert entry.experiment_id == "exp-1"

    @pytest.mark.asyncio
    async def test_selection_publisher_publishes_event(self, service):
        # enable the selection stream on the shared emitter
        service._events._selection = AsyncMock()
        service._gate_service.evaluate = AsyncMock(return_value=None)
        service._motor_client.select = AsyncMock(
            return_value={
                "arm": {"id": "arm-1", "name": "control", "index": 0},
                "policy": "BetaTSPolicy",
            }
        )

        await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[],
            context_metadata={},
        )
        await service._events.drain()

        service._events._selection.publish.assert_called_once()
        # policy comes from the motor response, not a redis re-fetch
        published = service._events._selection.publish.call_args.args[0]
        assert published.policy == "BetaTSPolicy"
        service._redis.get_experiment.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_publisher_no_publish(self, service):
        service._events._selection = None
        service._gate_service.evaluate = AsyncMock(return_value=None)
        service._motor_client.select = AsyncMock(
            return_value={"arm": {"id": "arm-1", "name": "control", "index": 0}}
        )

        # should not raise
        await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[],
            context_metadata={},
        )

    @pytest.mark.asyncio
    async def test_paused_serves_pool_arm_zero_no_token(self, service):
        from proxysvc.mod.experiment.cache import ExperimentState

        service._experiment_service.get_state = AsyncMock(
            return_value=ExperimentState(
                enabled=False,
                pool={"arms": [{"id": "arm-1", "name": "control", "index": 0}]},
            )
        )
        service._gate_service.get_config = AsyncMock(return_value=None)

        result = await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[1.0],
            context_metadata={},
        )

        assert result["is_default"] is True
        assert result["request_id"] is None
        assert result["arm"]["index"] == 0
        # paused experiments never reach the gate or motor
        service._gate_service.evaluate.assert_not_called()
        service._motor_client.select.assert_not_called()

    @pytest.mark.asyncio
    async def test_paused_gated_serves_default_arm(self, service):
        from factories import make_gate_config
        from proxysvc.mod.experiment.cache import ExperimentState

        service._experiment_service.get_state = AsyncMock(
            return_value=ExperimentState(
                enabled=False,
                pool={"arms": [{"id": "arm-1", "name": "control", "index": 0}]},
            )
        )
        committed = BaseArmModel(name="committed", id="arm-9", index=2)
        service._gate_service.get_config = AsyncMock(
            return_value=make_gate_config(committed_arm=committed)
        )

        result = await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[1.0],
            context_metadata={},
        )

        assert result["is_default"] is True
        assert result["request_id"] is None
        assert result["arm"]["id"] == "arm-9"
        assert result["arm"]["index"] == 2
        service._motor_client.select.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_experiment_routes_to_motor(self, service):
        from proxysvc.mod.experiment.cache import ExperimentState

        service._experiment_service.get_state = AsyncMock(
            return_value=ExperimentState(enabled=True, pool={})
        )
        service._gate_service.evaluate = AsyncMock(return_value=None)
        service._motor_client.select = AsyncMock(
            return_value={"arm": {"id": "arm-2", "name": "variant", "index": 1}}
        )

        result = await service.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[1.0],
            context_metadata={},
        )

        assert result["is_default"] is False
        assert result["request_id"] is not None
        service._motor_client.select.assert_called_once()


class TestProxyServiceFeed:

    @pytest.mark.asyncio
    async def test_feed_decodes_token_publishes_event(self, service):
        # create a real token
        token = SelectionToken.encode(
            secret=service._settings.token_secret_bytes,
            tenant_id="t-1",
            experiment_id="exp-1",
            arm_index=0,
            context_id="ctx-1",
            context_vector=[1.0],
            context_metadata={"k": "v"},
        )

        result = await service.feed(request_id=token, reward=1.0)
        await service._events.drain()

        assert result is True
        service._events._feedback.publish.assert_called_once()
        event = service._events._feedback.publish.call_args[0][0]
        assert event.tenant_id == "t-1"
        assert event.experiment_id == "exp-1"
        assert event.reward == 1.0

    @pytest.mark.asyncio
    async def test_feed_invalid_token_raises(self, service):
        with pytest.raises(TokenInvalidError):
            await service.feed(request_id="bad-token", reward=1.0)

    @pytest.mark.asyncio
    async def test_feed_empty_token_noops(self, service):
        # a client echoing back the null token from a paused selection must not
        # error; feed returns False and publishes nothing.
        result = await service.feed(request_id="", reward=1.0)
        await service._events.drain()

        assert result is False
        service._events._feedback.publish.assert_not_called()


class TestProxyServiceHealth:

    @pytest.mark.asyncio
    async def test_health_redis_up(self, service):
        service._redis.client.ping = AsyncMock(return_value=True)
        assert await service.health() is True

    @pytest.mark.asyncio
    async def test_health_redis_down(self, service):
        service._redis.client.ping = AsyncMock(side_effect=ConnectionError("down"))
        assert await service.health() is False

    @pytest.mark.asyncio
    async def test_motor_health_delegates(self, service):
        service._motor_client.health = AsyncMock(return_value=True)
        assert await service.motor_health() is True

    @pytest.mark.asyncio
    async def test_motor_health_exception_returns_false(self, service):
        service._motor_client.health = AsyncMock(side_effect=RuntimeError("broken"))
        assert await service.motor_health() is False

    @pytest.mark.asyncio
    async def test_cortex_health_delegates(self, service):
        service._cortex_client.health = AsyncMock(return_value=True)
        assert await service.cortex_health() is True


class TestProxyServicePoolCRUD:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.pool.service.get_session")
    async def test_create_pool(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        pool = _make_pool_record()
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=pool)

        with patch("proxysvc.mod.pool.service.PoolRepository", return_value=mock_repo):
            result = await service.create_pool("t-1", "Test Pool", [])

        assert result["id"] == "pool-1"
        assert result["name"] == "Test Pool"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.pool.service.get_session")
    async def test_get_pool_found(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        pool = _make_pool_record()
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=pool)

        with patch("proxysvc.mod.pool.service.PoolRepository", return_value=mock_repo):
            result = await service.get_pool("t-1", "pool-1")

        assert result is not None
        assert result["id"] == "pool-1"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.pool.service.get_session")
    async def test_get_pool_not_found(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        with patch("proxysvc.mod.pool.service.PoolRepository", return_value=mock_repo):
            result = await service.get_pool("t-1", "pool-1")

        assert result is None

    @pytest.mark.asyncio
    @patch("proxysvc.mod.pool.service.get_session")
    async def test_list_pools(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        pools = [_make_pool_record(id="p-1"), _make_pool_record(id="p-2")]
        mock_repo = AsyncMock()
        mock_repo.list = AsyncMock(return_value=pools)

        with patch("proxysvc.mod.pool.service.PoolRepository", return_value=mock_repo):
            result = await service.list_pools("t-1")

        assert len(result) == 2

    @pytest.mark.asyncio
    @patch("proxysvc.mod.pool.service.get_session")
    async def test_delete_pool(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.delete = AsyncMock(return_value=True)

        mock_exp_repo = AsyncMock()
        mock_exp_repo.list_by_pool = AsyncMock(return_value=[])

        with (
            patch(
                "proxysvc.mod.pool.service.ExperimentRepository",
                return_value=mock_exp_repo,
            ),
            patch("proxysvc.mod.pool.service.PoolRepository", return_value=mock_repo),
        ):
            result = await service.delete_pool("t-1", "pool-1")

        assert result is True

    @pytest.mark.asyncio
    @patch("proxysvc.mod.pool.service.get_session")
    async def test_delete_pool_with_experiments_raises(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        linked = MagicMock()
        linked.name = "exp-1"
        mock_exp_repo = AsyncMock()
        mock_exp_repo.list_by_pool = AsyncMock(return_value=[linked])

        with patch(
            "proxysvc.mod.pool.service.ExperimentRepository",
            return_value=mock_exp_repo,
        ):
            with pytest.raises(PoolHasExperimentsError):
                await service.delete_pool("t-1", "pool-1")


class TestProxyServiceExperimentCRUD:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_create_experiment_syncs_redis(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record()
        pool = _make_pool_record()
        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=0)
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
                name="Test Experiment",
                pool_id="pool-1",
                policy="BetaTSPolicy",
                policy_params={},
                enabled=True,
            )

        assert result["id"] == "exp-1"
        # redis sync should have been called
        service._redis.set_experiment.assert_called_once()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_create_experiment_with_gate_syncs_gate(
        self, mock_get_session, service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record()
        pool = _make_pool_record()
        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=0)
        mock_exp_repo.create = AsyncMock(return_value=exp)
        mock_exp_repo.get = AsyncMock(return_value=exp)
        mock_pool_repo = AsyncMock()
        mock_pool_repo.get = AsyncMock(return_value=pool)

        from factories import make_gate_config

        gate_config = make_gate_config()
        mock_gate_repo = AsyncMock()
        mock_gate_repo.get = AsyncMock(return_value=MagicMock())
        mock_gate_repo.to_config = MagicMock(return_value=gate_config)

        from proxysvc.mod.gate.schema import GateConfigRequest

        with (
            patch(
                "proxysvc.mod.experiment.service.ExperimentRepository",
                return_value=mock_exp_repo,
            ),
            patch(
                "proxysvc.mod.experiment.service.PoolRepository",
                return_value=mock_pool_repo,
            ),
            patch(
                "proxysvc.mod.experiment.service.FeatureGateRepository",
                return_value=mock_gate_repo,
            ),
        ):
            result = await service.create_experiment(
                tenant_id="t-1",
                name="Test Experiment",
                pool_id="pool-1",
                policy="BetaTSPolicy",
                policy_params={},
                enabled=True,
                feature_gate_config=GateConfigRequest(
                    enabled=True, rollout_percentage=50.0
                ),
            )

        assert result["id"] == "exp-1"
        service._gate_service.set_config.assert_called_once()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_create_auto_experiment_scopes_learners(
        self, mock_get_session, service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        parent = _make_experiment_record(id="meta-1", policy="MetaBanditPolicy")
        pool = _make_pool_record()

        created_records: list = []

        async def fake_create(**kwargs):
            idx = len(created_records)
            record = _make_experiment_record(
                id=f"exp-{idx}" if idx else "meta-1",
                name=kwargs["name"],
                policy=kwargs["policy"],
                policy_params=kwargs.get("policy_params", {}),
                enabled=kwargs.get("enabled", True),
            )
            created_records.append((kwargs, record))
            return record

        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=0)
        mock_exp_repo.create = AsyncMock(side_effect=fake_create)
        mock_exp_repo.update = AsyncMock()
        mock_exp_repo.get = AsyncMock(return_value=parent)
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
            result = await service.create_meta_experiment(
                tenant_id="t-1",
                name="Auto Exp",
                pool_id="pool-1",
                policy_params={
                    "reward_type": "continuous",
                    "use_context": True,
                    "dim": 8,
                },
                enabled=True,
            )

        assert result["id"] == "meta-1"

        # first create should be the meta parent
        parent_kwargs, _ = created_records[0]
        assert parent_kwargs["policy"] == "MetaBanditPolicy"
        assert parent_kwargs["enabled"] is True

        # remaining creates should be contextual learners with dim injected
        learner_calls = created_records[1:]
        assert len(learner_calls) >= 2
        for kwargs, _ in learner_calls:
            assert kwargs["meta_experiment_id"] == "meta-1"
            assert kwargs["policy_params"]["dim"] == 8
            assert kwargs["policy"] in {"LinTSPolicy", "LinUCBPolicy"}

        # parent is updated once with the learner id list after creation
        mock_exp_repo.update.assert_called_once()
        _, update_kwargs = mock_exp_repo.update.call_args
        learners_list = update_kwargs["policy_params"]["learners"]
        assert len(learners_list) == len(learner_calls)

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_create_auto_experiment_attaches_feature_gate(
        self, mock_get_session, service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        parent = _make_experiment_record(id="meta-1", policy="MetaBanditPolicy")
        pool = _make_pool_record()

        mock_exp_repo = AsyncMock()
        mock_exp_repo.count_active = AsyncMock(return_value=0)
        mock_exp_repo.create = AsyncMock(return_value=parent)
        mock_exp_repo.update = AsyncMock()
        mock_exp_repo.get = AsyncMock(return_value=parent)
        mock_pool_repo = AsyncMock()
        mock_pool_repo.get = AsyncMock(return_value=pool)

        from factories import make_gate_config

        gate_config = make_gate_config()
        mock_gate_repo = AsyncMock()
        mock_gate_repo.get = AsyncMock(return_value=MagicMock())
        mock_gate_repo.to_config = MagicMock(return_value=gate_config)

        from proxysvc.mod.gate.schema import GateConfigRequest

        with (
            patch(
                "proxysvc.mod.experiment.service.ExperimentRepository",
                return_value=mock_exp_repo,
            ),
            patch(
                "proxysvc.mod.experiment.service.PoolRepository",
                return_value=mock_pool_repo,
            ),
            patch(
                "proxysvc.mod.experiment.service.FeatureGateRepository",
                return_value=mock_gate_repo,
            ),
        ):
            await service.create_meta_experiment(
                tenant_id="t-1",
                name="Auto Exp",
                pool_id="pool-1",
                policy_params={"reward_type": "binary", "use_context": False},
                enabled=True,
                feature_gate_config=GateConfigRequest(
                    enabled=True, rollout_percentage=25.0
                ),
            )

        # feature_gate_config must be forwarded to the meta parent's create call
        first_create_kwargs = mock_exp_repo.create.call_args_list[0].kwargs
        assert first_create_kwargs["policy"] == "MetaBanditPolicy"
        assert first_create_kwargs["feature_gate_config"] is not None
        service._gate_service.set_config.assert_called_once_with(
            "t-1", "meta-1", gate_config
        )

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_update_experiment_syncs_redis(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record()
        pool = _make_pool_record()
        mock_exp_repo = AsyncMock()
        mock_exp_repo.update = AsyncMock(return_value=exp)
        mock_pool_repo = AsyncMock()
        mock_pool_repo.get = AsyncMock(return_value=pool)

        # get_session is called twice: once for update, once for _sync_experiment_to_redis
        mock_exp_repo.get = AsyncMock(return_value=exp)

        service._experiment_service._cache.invalidate = MagicMock()

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
            result = await service.update_experiment("t-1", "exp-1", name="Updated")

        assert result is not None
        service._redis.set_experiment.assert_called_once()
        # pausing/updating drops the local l1 so the change takes effect at once
        service._experiment_service._cache.invalidate.assert_called_once_with(
            "t-1", "exp-1"
        )

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_delete_experiment_cleans_redis(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.delete = AsyncMock(return_value=True)

        with patch(
            "proxysvc.mod.experiment.service.ExperimentRepository",
            return_value=mock_repo,
        ):
            result = await service.delete_experiment("t-1", "exp-1")

        assert result is True
        service._redis.delete_experiment.assert_called_once_with("t-1", "exp-1")
        service._gate_service.delete_config.assert_called_once_with("t-1", "exp-1")

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_reset_experiment_clears_params_and_flushes(
        self, mock_get_session, service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record(enabled=False)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=exp)

        with patch(
            "proxysvc.mod.experiment.service.ExperimentRepository",
            return_value=mock_repo,
        ):
            result = await service.reset_experiment("t-1", "exp-1", actor_id="u-1")

        assert result is not None
        assert result["id"] == "exp-1"
        service._cortex_client.flush_batch.assert_called_once_with("exp-1")
        service._redis.delete_params.assert_called_once_with("t-1", "exp-1")
        service._events._feedback.publish.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_reset_experiment_running_raises(self, mock_get_session, service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record(enabled=True)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=exp)

        with patch(
            "proxysvc.mod.experiment.service.ExperimentRepository",
            return_value=mock_repo,
        ):
            with pytest.raises(ExperimentRunningError):
                await service.reset_experiment("t-1", "exp-1")

        service._redis.delete_params.assert_not_called()
        service._cortex_client.flush_batch.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_reset_experiment_not_found_returns_none(
        self, mock_get_session, service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        with patch(
            "proxysvc.mod.experiment.service.ExperimentRepository",
            return_value=mock_repo,
        ):
            result = await service.reset_experiment("t-1", "missing")

        assert result is None
        service._redis.delete_params.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.experiment.service.get_session")
    async def test_reset_experiment_survives_cortex_failure(
        self, mock_get_session, service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        exp = _make_experiment_record(enabled=False)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=exp)
        service._cortex_client.flush_batch = AsyncMock(
            side_effect=RuntimeError("cortex down")
        )

        with patch(
            "proxysvc.mod.experiment.service.ExperimentRepository",
            return_value=mock_repo,
        ):
            result = await service.reset_experiment("t-1", "exp-1")

        assert result is not None
        service._redis.delete_params.assert_called_once_with("t-1", "exp-1")


class TestProxyServiceGateConfig:

    @pytest.mark.asyncio
    async def test_get_gate_config_found(self, service):
        from factories import make_gate_config

        config = make_gate_config()
        service._gate_service.get_config = AsyncMock(return_value=config)

        result = await service.get_gate_config("t-1", "exp-1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_gate_config_not_found(self, service):
        service._gate_service.get_config = AsyncMock(return_value=None)

        result = await service.get_gate_config("t-1", "exp-1")
        assert result is None
