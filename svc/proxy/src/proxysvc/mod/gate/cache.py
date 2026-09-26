from __future__ import annotations

from cachebox import TTLCache

from qbrixstore.redis import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.cache import TwoTierCache
from proxysvc.mod.gate.config import FeatureGateConfig

_GATE_NAMESPACE = "qbrix:tenant"


class GateConfigCache:
    """two-level cache for feature gate configurations.

    l1: in-memory TTLCache (microsecond access)
    l2: redis (millisecond access, shared across proxy replicas)

    both levels expire, and neither is the source of truth — postgres is. the
    read-through behind this cache (`GateService.get_config`) turns a miss into
    a postgres read, so the *absence* of a gate has to be cached too: most
    experiments have no gate at all, and the select path asks about every one of
    them on every request. the negative marker is l1-only and short-lived —
    a stale "no gate" costs at most one l1 ttl of ungated traffic after a gate
    is created on another replica, which is what the positive entry already
    costs after an update.
    """

    def __init__(self, redis: RedisClient, settings: ProxySettings) -> None:
        self._tier: TwoTierCache[FeatureGateConfig] = TwoTierCache(
            redis=redis.client,
            model=FeatureGateConfig,
            namespace=_GATE_NAMESPACE,
            l1_maxsize=settings.gate_cache_maxsize,
            l1_ttl=settings.gate_cache_ttl,
            l2_ttl=settings.gate_redis_ttl,
        )
        self._absent: TTLCache = TTLCache(
            maxsize=settings.gate_cache_maxsize, ttl=settings.gate_cache_ttl
        )

    @staticmethod
    def _absent_key(tenant_id: str, experiment_id: str) -> str:
        return f"{tenant_id}:{experiment_id}"

    async def get(self, tenant_id: str, experiment_id: str) -> FeatureGateConfig | None:
        """get gate config from cache hierarchy (l1 -> l2)."""
        return await self._tier.get(tenant_id, "gate", experiment_id)

    async def set(
        self, tenant_id: str, experiment_id: str, config: FeatureGateConfig
    ) -> None:
        """set gate config in both cache levels."""
        self._absent.pop(self._absent_key(tenant_id, experiment_id), None)
        await self._tier.set(tenant_id, "gate", experiment_id, value=config)

    async def delete(self, tenant_id: str, experiment_id: str) -> None:
        """delete gate config from both cache levels."""
        await self._tier.delete(tenant_id, "gate", experiment_id)
        self.mark_absent(tenant_id, experiment_id)

    def invalidate(self, tenant_id: str, experiment_id: str) -> None:
        """invalidate l1 cache entry only."""
        self._tier.invalidate(tenant_id, "gate", experiment_id)
        self._absent.pop(self._absent_key(tenant_id, experiment_id), None)

    def known_absent(self, tenant_id: str, experiment_id: str) -> bool:
        """true if postgres was recently seen to hold no gate for this experiment."""
        return self._absent_key(tenant_id, experiment_id) in self._absent

    def mark_absent(self, tenant_id: str, experiment_id: str) -> None:
        """record that postgres holds no gate for this experiment."""
        self._absent[self._absent_key(tenant_id, experiment_id)] = True
