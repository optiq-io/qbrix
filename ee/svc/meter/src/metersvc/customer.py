from __future__ import annotations

from cachebox import TTLCache
from sqlalchemy import select

from qbrixstore.postgres.models import StripeCustomer
from qbrixstore.postgres.models import Subscription
from qbrixstore.postgres.session import get_session

# tiers that bill selections; free is hard-capped and never metered to stripe.
# kept local so metersvc does not depend on proxysvc.
PAID_TIERS = frozenset({"starter", "growth", "scale", "enterprise"})

# sentinel to tell a cache miss apart from a cached negative result (None).
_MISS = object()


class CustomerCache:
    """read-through cache mapping tenant_id -> stripe customer id for active
    paid tenants.

    a miss loads from postgres; results (negative ones included) are held for a
    short ttl so a tenant's repeated buckets do not each hit the database.
    """

    def __init__(self, *, maxsize: int, ttl: float):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)

    async def get(self, tenant_id: str) -> str | None:
        """return the stripe customer id for a billable tenant, else None."""
        cached = self._cache.get(tenant_id, _MISS)
        if cached is not _MISS:
            return cached
        customer_id = await self._load(tenant_id)
        self._cache[tenant_id] = customer_id
        return customer_id

    async def _load(self, tenant_id: str) -> str | None:
        async with get_session() as session:
            subscription = await self._load_subscription(session, tenant_id)
            if (
                subscription is None
                or subscription.status != "active"
                or subscription.plan_tier not in PAID_TIERS
            ):
                return None

            customer = await self._load_customer(session, tenant_id)
            if customer is None:
                return None

            return customer.stripe_customer_id

    @staticmethod
    async def _load_subscription(session, tenant_id: str) -> Subscription | None:
        stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def _load_customer(session, tenant_id: str) -> StripeCustomer | None:
        stmt = select(StripeCustomer).where(StripeCustomer.tenant_id == tenant_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    def invalidate(self, tenant_id: str) -> None:
        self._cache.pop(tenant_id, None)
