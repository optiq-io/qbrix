from __future__ import annotations

from qbrixstore.redis.client import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.entitlements import Edition
from proxysvc.ee.plans import TIER_ORDER
from proxysvc.ee.plans import features_for
from proxysvc.ee.plans import has_feature
from proxysvc.ee.plans import limits_for
from proxysvc.ee.metering.meter import SelectionMeter
from proxysvc.ee.metering.resolver import UsageResolver


class PlanEntitlements:
    """cloud: limits and features from the plan tier, selections metered.

    a feature is granted when the tier includes it and the deployment offers
    it; offered but not included is locked, which the console sells.
    """

    edition: Edition = "cloud"

    def __init__(
        self,
        *,
        redis: RedisClient,
        settings: ProxySettings,
        offered: frozenset[str],
    ):
        self._redis = redis
        self._offered = offered
        self._resolver = UsageResolver(settings=settings)
        self._meter = SelectionMeter(
            redis=redis, resolver=self._resolver, settings=settings
        )

    def limits(self, tier: str) -> dict[str, int]:
        return limits_for(tier)

    def features(self, tier: str) -> frozenset[str]:
        return frozenset(features_for(tier)) & self._offered

    def locked_features(self, tier: str) -> frozenset[str]:
        return self._offered - self.features(tier)

    def upgrade_tiers(self, feature: str) -> list[str]:
        return [t for t in TIER_ORDER if has_feature(t, feature)]

    async def on_selection(self, tenant_id: str) -> None:
        await self._meter.record_and_enforce(tenant_id)

    async def usage(self, tenant_id: str) -> dict[str, float]:
        ctx = await self._resolver.resolve(tenant_id)
        return {
            "selections_this_period": await self._redis.get_selection_usage(
                tenant_id, ctx.period_key
            ),
            "period_start": ctx.period_start.timestamp(),
            "period_end": ctx.period_end.timestamp(),
        }

    def invalidate(self, tenant_id: str) -> None:
        self._resolver.invalidate(tenant_id)
