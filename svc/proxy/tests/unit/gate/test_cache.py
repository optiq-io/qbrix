"""unit tests for GateConfigCache two-level caching."""

from __future__ import annotations

import pytest

from proxysvc.mod.gate.cache import GateConfigCache

from factories import make_gate_config

# l1 key for ("t-1", "exp-1") given namespace "qbrix:tenant"
# format: "qbrix:tenant:<tenant_id>:gate:<experiment_id>"
_L1_KEY = "qbrix:tenant:t-1:gate:exp-1"


class TestGateConfigCacheGet:

    async def test_l1_hit_returns_cached(self, mock_redis, proxy_settings):
        cache = GateConfigCache(mock_redis, proxy_settings)
        config = make_gate_config()

        # populate l1 directly via the inner tier
        cache._tier._l1[_L1_KEY] = config

        result = await cache.get("t-1", "exp-1")
        assert result is config
        # raw redis client should not have been called
        mock_redis.client.get.assert_not_called()

    async def test_l1_miss_l2_hit_populates_l1(self, mock_redis, proxy_settings):
        cache = GateConfigCache(mock_redis, proxy_settings)
        config = make_gate_config()
        # redis returns json-serialized config
        mock_redis.client.get.return_value = config.model_dump_json()

        result = await cache.get("t-1", "exp-1")

        assert result is not None
        assert result.experiment.experiment_id == config.experiment.experiment_id
        mock_redis.client.get.assert_called_once_with(_L1_KEY)
        # l1 should now be populated
        assert _L1_KEY in cache._tier._l1

    async def test_l1_miss_l2_miss_returns_none(self, mock_redis, proxy_settings):
        cache = GateConfigCache(mock_redis, proxy_settings)
        mock_redis.client.get.return_value = None

        result = await cache.get("t-1", "exp-1")
        assert result is None


class TestGateConfigCacheSet:

    async def test_set_writes_to_redis_and_l1(self, mock_redis, proxy_settings):
        cache = GateConfigCache(mock_redis, proxy_settings)
        config = make_gate_config()

        await cache.set("t-1", "exp-1", config)

        mock_redis.client.set.assert_called_once_with(
            _L1_KEY,
            config.model_dump_json(),
            ex=proxy_settings.gate_redis_ttl,
        )
        assert cache._tier._l1[_L1_KEY] is config


class TestGateConfigCacheDelete:

    async def test_delete_removes_from_both_levels(self, mock_redis, proxy_settings):
        cache = GateConfigCache(mock_redis, proxy_settings)
        config = make_gate_config()
        cache._tier._l1[_L1_KEY] = config

        await cache.delete("t-1", "exp-1")

        mock_redis.client.delete.assert_called_once_with(_L1_KEY)
        assert _L1_KEY not in cache._tier._l1


class TestGateConfigCacheInvalidate:

    def test_invalidate_removes_l1_only(self, mock_redis, proxy_settings):
        cache = GateConfigCache(mock_redis, proxy_settings)
        config = make_gate_config()
        cache._tier._l1[_L1_KEY] = config

        cache.invalidate("t-1", "exp-1")

        assert _L1_KEY not in cache._tier._l1
        # redis delete must not be called on invalidate
        mock_redis.client.delete.assert_not_called()
