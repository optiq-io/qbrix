"""unit tests for GateService orchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from proxysvc.core.error import GateExistsError
from proxysvc.mod.gate import GateService
from proxysvc.mod.gate.schema import GateConfigRequest

from factories import make_gate_config


def cache_mock(config=None, absent=True):
    """a GateConfigCache double whose sync methods stay sync.

    `known_absent`/`mark_absent`/`invalidate` are not coroutines; a bare
    AsyncMock would make `known_absent` return a truthy coroutine and hide the
    read-through entirely. `absent` defaults to True so a test that only cares
    about the cache never reaches postgres.
    """
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=config)
    cache.known_absent = MagicMock(return_value=absent)
    cache.mark_absent = MagicMock()
    cache.invalidate = MagicMock()
    return cache


class TestGateServiceEvaluate:

    @pytest.mark.asyncio
    async def test_no_config_returns_none(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        service._cache = cache_mock(None)

        result = await service.evaluate("t-1", "exp-1", "ctx-1", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_config_returns_committed_arm(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        # enabled gate with 0% rollout => context outside rollout => committed arm
        config = make_gate_config(enabled=True, rollout_percentage=0.0)
        service._cache = cache_mock(config)

        result = await service.evaluate("t-1", "exp-1", "ctx-1", {})
        assert result is not None
        assert result.index == 0

    @pytest.mark.asyncio
    async def test_disabled_gate_returns_none(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        # disabled gate does no gating => bandit selection proceeds
        config = make_gate_config(enabled=False)
        service._cache = cache_mock(config)

        result = await service.evaluate("t-1", "exp-1", "ctx-1", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_control_returns_none(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        # enabled + 100% rollout + no rules => control returns None
        config = make_gate_config(enabled=True, rollout_percentage=100.0, rules=[])
        service._cache = cache_mock(config)

        result = await service.evaluate("t-1", "exp-1", "ctx-1", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none_fail_open(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        service._cache = cache_mock()
        service._cache.get = AsyncMock(side_effect=RuntimeError("cache exploded"))

        result = await service.evaluate("t-1", "exp-1", "ctx-1", {})
        assert result is None

    @pytest.mark.asyncio
    @patch("proxysvc.mod.gate.service.get_session")
    async def test_expired_cache_still_gates(
        self, mock_get_session, mock_redis, proxy_settings
    ):
        """both cache levels expire; the gate must not expire with them."""
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        config = make_gate_config(enabled=True, rollout_percentage=0.0)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=MagicMock())
        mock_repo.to_config = MagicMock(return_value=config)

        service = GateService(mock_redis, proxy_settings)
        service._cache = cache_mock(None, absent=False)

        with patch(
            "proxysvc.mod.gate.service.FeatureGateRepository", return_value=mock_repo
        ):
            result = await service.evaluate("t-1", "exp-1", "ctx-1", {})

        assert result is not None
        assert result.index == 0


class TestGateServiceConfig:

    @pytest.mark.asyncio
    async def test_get_config_delegates(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        config = make_gate_config()
        service._cache = cache_mock(config)

        result = await service.get_config("t-1", "exp-1")
        assert result is config
        service._cache.get.assert_called_once_with("t-1", "exp-1")

    @pytest.mark.asyncio
    async def test_get_config_known_absent_skips_postgres(
        self, mock_redis, proxy_settings
    ):
        service = GateService(mock_redis, proxy_settings)
        service._cache = cache_mock(None, absent=True)

        with patch("proxysvc.mod.gate.service.get_session") as mock_get_session:
            assert await service.get_config("t-1", "exp-1") is None
            mock_get_session.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.gate.service.get_session")
    async def test_get_config_reads_through_scoped_to_tenant(
        self, mock_get_session, mock_redis, proxy_settings
    ):
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        config = make_gate_config()
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=MagicMock())
        mock_repo.to_config = MagicMock(return_value=config)

        service = GateService(mock_redis, proxy_settings)
        service._cache = cache_mock(None, absent=False)

        with patch(
            "proxysvc.mod.gate.service.FeatureGateRepository", return_value=mock_repo
        ) as mock_repo_cls:
            result = await service.get_config("t-1", "exp-1")

        assert result is config
        # the tenant now scopes the repository itself, so that is where it has
        # to arrive — a lookup that forgot it could not be expressed
        assert mock_repo_cls.call_args.args[1] == "t-1"
        mock_repo.get.assert_called_once_with("exp-1")
        service._cache.set.assert_called_once_with("t-1", "exp-1", config)

    @pytest.mark.asyncio
    @patch("proxysvc.mod.gate.service.get_session")
    async def test_get_config_caches_absence(
        self, mock_get_session, mock_redis, proxy_settings
    ):
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        service = GateService(mock_redis, proxy_settings)
        service._cache = cache_mock(None, absent=False)

        with patch(
            "proxysvc.mod.gate.service.FeatureGateRepository", return_value=mock_repo
        ):
            result = await service.get_config("t-1", "exp-1")

        assert result is None
        service._cache.mark_absent.assert_called_once_with("t-1", "exp-1")
        service._cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_config_delegates(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        config = make_gate_config()
        service._cache = cache_mock()
        service._cache.set = AsyncMock()

        await service.set_config("t-1", "exp-1", config)
        service._cache.set.assert_called_once_with("t-1", "exp-1", config)

    @pytest.mark.asyncio
    async def test_delete_config_delegates(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        service._cache = cache_mock()
        service._cache.delete = AsyncMock()

        await service.delete_config("t-1", "exp-1")
        service._cache.delete.assert_called_once_with("t-1", "exp-1")

    def test_invalidate_delegates(self, mock_redis, proxy_settings):
        service = GateService(mock_redis, proxy_settings)
        service._cache = MagicMock()
        service._cache.invalidate = MagicMock()

        service.invalidate("t-1", "exp-1")
        service._cache.invalidate.assert_called_once_with("t-1", "exp-1")


class TestGateServiceConfigCrud:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.gate.service.get_session")
    async def test_create_gate_config(
        self, mock_get_session, mock_redis, proxy_settings
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        gate_config = make_gate_config()
        mock_repo = AsyncMock()
        mock_repo.exists = AsyncMock(return_value=False)
        mock_repo.create = AsyncMock()
        mock_repo.get = AsyncMock(return_value=MagicMock())
        mock_repo.to_config = MagicMock(return_value=gate_config)

        service = GateService(mock_redis, proxy_settings, events=MagicMock())
        service._cache = cache_mock()

        with patch(
            "proxysvc.mod.gate.service.FeatureGateRepository", return_value=mock_repo
        ):
            result = await service.create_gate_config(
                "t-1", "exp-1", GateConfigRequest(enabled=True)
            )

        assert result is not None
        service._cache.set.assert_called_once()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.gate.service.get_session")
    async def test_create_gate_config_conflicts_when_one_exists(
        self, mock_get_session, mock_redis, proxy_settings
    ):
        """experiment_id is unique, so this used to surface as a 500."""
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.exists = AsyncMock(return_value=True)
        mock_repo.create = AsyncMock()

        service = GateService(mock_redis, proxy_settings, events=MagicMock())
        service._cache = cache_mock()

        with patch(
            "proxysvc.mod.gate.service.FeatureGateRepository", return_value=mock_repo
        ):
            with pytest.raises(GateExistsError):
                await service.create_gate_config(
                    "t-1", "exp-1", GateConfigRequest(enabled=True)
                )

        mock_repo.create.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.gate.service.get_session")
    async def test_update_gate_config_invalidates_l1(
        self, mock_get_session, mock_redis, proxy_settings
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        gate_config = make_gate_config()
        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock(return_value=MagicMock())
        mock_repo.get = AsyncMock(return_value=MagicMock())
        mock_repo.to_config = MagicMock(return_value=gate_config)

        service = GateService(mock_redis, proxy_settings, events=MagicMock())
        service._cache = cache_mock()

        with patch(
            "proxysvc.mod.gate.service.FeatureGateRepository", return_value=mock_repo
        ):
            result = await service.update_gate_config(
                "t-1", "exp-1", GateConfigRequest(enabled=False)
            )

        assert result is not None
        service._cache.invalidate.assert_called_once_with("t-1", "exp-1")
        service._cache.set.assert_called_once()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.gate.service.get_session")
    async def test_update_gate_config_missing_returns_none(
        self, mock_get_session, mock_redis, proxy_settings
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock(return_value=None)

        service = GateService(mock_redis, proxy_settings, events=MagicMock())
        service._cache = cache_mock()

        with patch(
            "proxysvc.mod.gate.service.FeatureGateRepository", return_value=mock_repo
        ):
            result = await service.update_gate_config(
                "t-1", "exp-1", GateConfigRequest(enabled=False)
            )

        assert result is None
        service._cache.set.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.gate.service.get_session")
    async def test_delete_gate_config(
        self, mock_get_session, mock_redis, proxy_settings
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.delete = AsyncMock(return_value=True)

        service = GateService(mock_redis, proxy_settings, events=MagicMock())
        service._cache = cache_mock()

        with patch(
            "proxysvc.mod.gate.service.FeatureGateRepository", return_value=mock_repo
        ):
            result = await service.delete_gate_config("t-1", "exp-1")

        assert result is True
        service._cache.delete.assert_called_once_with("t-1", "exp-1")
