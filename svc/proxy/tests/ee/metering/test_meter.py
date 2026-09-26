"""unit tests for the selection meter (counter + free hard-cap + rollover)."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from proxysvc.config import ProxySettings
from proxysvc.core.error import UsageLimitError
from proxysvc.ee.metering.meter import SelectionMeter
from proxysvc.ee.metering.model import UsageContext


def _ctx(
    *,
    tier: str = "free",
    included: int = 100,
    period_key: str = "2026-07",
) -> UsageContext:
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    return UsageContext(
        tenant_id="t-1",
        tier=tier,
        included=included,
        period_key=period_key,
        period_start=start,
        period_end=start + timedelta(days=30),
    )


def _resolver(*contexts: UsageContext) -> AsyncMock:
    """a resolver returning each context in turn; the last one repeats.

    the meter re-resolves once before rejecting, so tests that exercise that
    path hand it a second context to find.
    """
    resolver = AsyncMock()
    if len(contexts) == 1:
        resolver.resolve = AsyncMock(return_value=contexts[0])
    else:
        resolver.resolve = AsyncMock(side_effect=list(contexts))
    resolver.invalidate = MagicMock()
    return resolver


def _meter(redis, ctx, *, cooldown_sec: float = 5.0) -> SelectionMeter:
    return SelectionMeter(
        redis=redis,
        resolver=_resolver(ctx),
        settings=ProxySettings(usage_recheck_cooldown_sec=cooldown_sec),
    )


def _redis(*, count: int = 1) -> AsyncMock:
    redis = AsyncMock()
    redis.incr_selection_usage = AsyncMock(return_value=count)
    redis.get_selection_usage = AsyncMock(return_value=count)
    return redis


class TestRecordAndEnforce:
    async def test_increments_and_returns_count(self):
        redis = _redis(count=5)
        meter = _meter(redis, _ctx())
        count = await meter.record_and_enforce("t-1")
        assert count == 5
        redis.incr_selection_usage.assert_awaited_once()

    async def test_free_over_quota_raises(self):
        meter = _meter(_redis(count=101), _ctx(tier="free", included=100))
        with pytest.raises(UsageLimitError):
            await meter.record_and_enforce("t-1")

    async def test_free_at_quota_boundary_allowed(self):
        # cap is count > included, so exactly-at-quota still serves
        meter = _meter(_redis(count=100), _ctx(tier="free", included=100))
        assert await meter.record_and_enforce("t-1") == 100

    async def test_paid_over_quota_never_blocked(self):
        meter = _meter(_redis(count=101), _ctx(tier="starter", included=100))
        assert await meter.record_and_enforce("t-1") == 101

    async def test_unlimited_tier_never_blocked(self):
        meter = _meter(_redis(count=10_000), _ctx(tier="enterprise", included=-1))
        assert await meter.record_and_enforce("t-1") == 10_000


class TestRejectionRecheck:
    """turning away a tenant who has already paid is the one staleness that
    costs money, so the meter re-resolves once before it rejects."""

    @staticmethod
    def _meter_with(resolver, *, count: int, cooldown_sec: float = 5.0):
        return SelectionMeter(
            redis=_redis(count=count),
            resolver=resolver,
            settings=ProxySettings(usage_recheck_cooldown_sec=cooldown_sec),
        )

    async def test_upgraded_tenant_is_not_rejected_on_a_stale_free_tier(self):
        """the cached context still says free; the authoritative one does not."""
        resolver = _resolver(
            _ctx(tier="free", included=100),
            _ctx(tier="starter", included=1_000_000),
        )
        meter = self._meter_with(resolver, count=101)

        assert await meter.record_and_enforce("t-1") == 101
        resolver.invalidate.assert_called_once_with("t-1")

    async def test_genuinely_over_quota_tenant_is_still_rejected(self):
        """the backstop must not become an escape hatch from enforcement."""
        resolver = _resolver(
            _ctx(tier="free", included=100),
            _ctx(tier="free", included=100),
        )
        meter = self._meter_with(resolver, count=101)

        with pytest.raises(UsageLimitError):
            await meter.record_and_enforce("t-1")

    async def test_recheck_is_cooled_down_per_tenant(self):
        """without the cooldown an over-quota tenant turns every rejected
        request into a database read — a free amplification of abuse."""
        resolver = _resolver(*[_ctx(tier="free", included=100)] * 6)
        meter = self._meter_with(resolver, count=101)

        for _ in range(3):
            with pytest.raises(UsageLimitError):
                await meter.record_and_enforce("t-1")

        # 3 cached resolves + exactly one authoritative re-resolve
        assert resolver.resolve.await_count == 4
        resolver.invalidate.assert_called_once_with("t-1")

    async def test_cooldown_is_scoped_to_the_tenant(self):
        resolver = _resolver(*[_ctx(tier="free", included=100)] * 6)
        meter = self._meter_with(resolver, count=101)

        for tenant_id in ("t-1", "t-2"):
            with pytest.raises(UsageLimitError):
                await meter.record_and_enforce(tenant_id)

        assert resolver.invalidate.call_count == 2

    async def test_no_recheck_when_the_tenant_is_within_quota(self):
        """the hot path must not pay for the rejection path."""
        resolver = _resolver(_ctx(tier="free", included=100))
        meter = self._meter_with(resolver, count=50)

        await meter.record_and_enforce("t-1")

        resolver.invalidate.assert_not_called()
        assert resolver.resolve.await_count == 1
