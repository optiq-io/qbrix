from __future__ import annotations

from datetime import datetime
from datetime import timezone

from cachebox import TTLCache
from qbrixstore.postgres.models import Subscription
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.session import get_session
from sqlalchemy import select

from proxysvc.config import ProxySettings
from proxysvc.ee.plans import PLAN_LIMITS
from proxysvc.ee.metering.model import UsageContext


def _calendar_month(now: datetime) -> tuple[datetime, datetime]:
    """utc calendar-month bounds [first-of-month 00:00, first-of-next-month 00:00)."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


class UsageResolver:
    """resolves a tenant to its tier + billing period, cached in-process.

    tier is taken from ``tenants.plan_tier``, the authoritative source; the
    period comes from the tenant's subscription when present, otherwise the
    current calendar month. only the resolved context is cached — never the
    live selection count.
    """

    def __init__(self, *, settings: ProxySettings):
        self._settings = settings
        self._cache: TTLCache = TTLCache(
            maxsize=settings.usage_cache_maxsize, ttl=settings.usage_cache_ttl
        )

    async def resolve(self, tenant_id: str) -> UsageContext:
        """resolve the tenant's tier + billing period, served from a short-ttl
        in-process cache to keep the hot path off postgres."""
        cached = self._cache.get(tenant_id)
        if cached is not None:
            return cached
        ctx = await self._load(tenant_id)
        self._cache[tenant_id] = ctx
        return ctx

    async def _load(self, tenant_id: str) -> UsageContext:
        async with get_session() as session:
            tier, subscription = await self._load_tier_and_subscription(
                session, tenant_id
            )

        now = datetime.now(timezone.utc)
        if subscription is not None and subscription.status == "active":
            period_start = subscription.current_period_start
            period_end = subscription.current_period_end
            period_key = period_start.date().isoformat()
        else:
            period_start, period_end = _calendar_month(now)
            period_key = period_start.strftime("%Y-%m")

        included = PLAN_LIMITS.get(tier, PLAN_LIMITS["free"])[
            "included_selections_per_month"
        ]
        return UsageContext(
            tenant_id=tenant_id,
            tier=tier,
            included=included,
            period_key=period_key,
            period_start=period_start,
            period_end=period_end,
        )

    @staticmethod
    async def _load_tier_and_subscription(
        session, tenant_id: str
    ) -> tuple[str, Subscription | None]:
        """one query: the tier and the billing period come from the same row.

        subscriptions.tenant_id is unique, so the outer join yields at most one
        row; an unknown tenant yields none and resolves to free.
        """
        stmt = (
            select(Tenant.plan_tier, Subscription)
            .outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
            .where(Tenant.id == tenant_id)
        )
        result = await session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return "free", None
        return row[0] or "free", row[1]

    def invalidate(self, tenant_id: str) -> None:
        self._cache.pop(tenant_id, None)
