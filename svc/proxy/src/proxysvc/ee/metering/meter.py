from __future__ import annotations

from datetime import datetime
from datetime import timezone

from cachebox import TTLCache
from qbrixstore.redis.client import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.error import UsageLimitError
from proxysvc.ee.metering.model import UsageContext
from proxysvc.ee.metering.resolver import UsageResolver

# keep the period counter alive past period end so a slightly late read still
# sees it before redis reclaims the key
_TTL_BUFFER_SEC = 2 * 24 * 60 * 60


class SelectionMeter:
    """per-tenant selection meter on the hot path.

    increments an atomic redis counter per billing period and hard-caps free
    tenants at their included quota. this counter is the fast *enforcement*
    layer — approximate and non-idempotent by design.
    billing itself is metered independently to stripe from the selection event
    stream (see the metersvc emitter), so this counter never bills.
    """

    def __init__(
        self,
        *,
        redis: RedisClient,
        resolver: UsageResolver,
        settings: ProxySettings,
    ):
        self._redis = redis
        self._resolver = resolver
        self._settings = settings
        self._recheck_cooldown: TTLCache = TTLCache(
            maxsize=settings.usage_cache_maxsize,
            ttl=settings.usage_recheck_cooldown_sec,
        )

    async def record_and_enforce(self, tenant_id: str) -> int:
        """count one selection and reject free tenants over their included quota
        with UsageLimitError. returns the new period count.
        """
        ctx = await self._resolver.resolve(tenant_id)
        count = await self._redis.incr_selection_usage(
            tenant_id, ctx.period_key, self._ttl_for(ctx)
        )
        if not self._over_quota(ctx, count):
            return count

        ctx = await self._recheck(tenant_id, ctx)
        if self._over_quota(ctx, count):
            raise UsageLimitError(
                "selection usage limit exceeded for the current billing period"
            )
        return count

    async def _recheck(self, tenant_id: str, ctx: UsageContext) -> UsageContext:
        """re-resolve authoritatively before turning a tenant away.

        a tenant who upgraded seconds ago can still be cached as free, and
        rejecting them is the one staleness that costs money. cooled down per
        tenant so a genuinely over-quota tenant cannot turn every rejected
        request into a database read.
        """
        if self._recheck_cooldown.get(tenant_id) is not None:
            return ctx
        self._recheck_cooldown[tenant_id] = True
        self._resolver.invalidate(tenant_id)
        return await self._resolver.resolve(tenant_id)

    @staticmethod
    def _over_quota(ctx: UsageContext, count: int) -> bool:
        return ctx.tier == "free" and 0 <= ctx.included < count

    @staticmethod
    def _ttl_for(ctx: UsageContext) -> int:
        now = datetime.now(timezone.utc)
        remaining = int((ctx.period_end - now).total_seconds())
        return max(remaining, 0) + _TTL_BUFFER_SEC
