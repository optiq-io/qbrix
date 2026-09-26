from __future__ import annotations

from qbrixstore.channel import TENANT_INVALIDATION_CHANNEL
from qbrixstore.config import RedisSettings
from qbrixstore.redis.pubsub import BroadcastBus


class TenantInvalidation(BroadcastBus):
    """cross-replica eviction signal for tenant entitlement caches.

    a tier change is written by whichever replica happens to serve the stripe
    webhook, but every replica caches the entitlements it derives. this
    broadcasts the tenant id so the others evict too.

    delivery is deliberately best-effort. the message carries no state — only
    a tenant id, on receipt of which subscribers drop cache entries and re-read
    postgres — and every such cache keeps its own ttl. a message lost to a
    disconnect therefore costs a few seconds of staleness rather than
    correctness.
    """

    def __init__(self, settings: RedisSettings | None = None):
        super().__init__(TENANT_INVALIDATION_CHANNEL, settings)


class LocalTenantInvalidation:
    """the same signal, confined to one process.

    for contexts with no redis to broadcast over — tests, and any partially
    wired process — where dropping the local caches is still required.
    """

    def __init__(self) -> None:
        self._callbacks: list = []

    def register(self, callback) -> None:
        self._callbacks.append(callback)

    async def publish(self, tenant_id: str, /) -> None:
        for callback in self._callbacks:
            callback(tenant_id)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None
