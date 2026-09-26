"""unit tests for tenant tier/period resolution (hybrid: tenant tier +
subscription period, else calendar month)."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Base
from qbrixstore.postgres.models import Subscription
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User

from proxysvc.config import ProxySettings
from proxysvc.ee.metering.resolver import UsageResolver


@pytest_asyncio.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(_session_module, "_engine", engine)
    monkeypatch.setattr(_session_module, "_session_factory", factory)
    yield factory
    await engine.dispose()


async def _seed(
    factory,
    *,
    tenant_id: str,
    tier: str,
    subscription: bool = False,
    subscription_tier: str | None = None,
) -> None:
    """seed a tenant. subscription_tier defaults to tier, and is set explicitly
    only to prove which column the resolver actually reads."""
    async with factory() as session:
        session.add(
            Tenant(id=tenant_id, name=tenant_id, slug=tenant_id, plan_tier=tier)
        )
        session.add(
            User(
                tenant_id=tenant_id,
                email=f"{tenant_id}@example.com",
                password_hash="x",
            )
        )
        if subscription:
            session.add(
                Subscription(
                    tenant_id=tenant_id,
                    stripe_subscription_id=f"sub_{tenant_id}",
                    stripe_customer_id=f"cus_{tenant_id}",
                    plan_tier=subscription_tier or tier,
                    status="active",
                    current_period_start=datetime(2026, 3, 15, tzinfo=timezone.utc),
                    current_period_end=datetime(2026, 4, 15, tzinfo=timezone.utc),
                )
            )
        await session.commit()


def _resolver() -> UsageResolver:
    return UsageResolver(settings=ProxySettings(usage_cache_maxsize=100))


class TestResolve:
    async def test_free_tenant_uses_calendar_month(self, db):
        await _seed(db, tenant_id="free-t", tier="free")
        ctx = await _resolver().resolve("free-t")
        assert ctx.tier == "free"
        assert ctx.included == 100_000
        assert ctx.period_start.day == 1
        assert ctx.period_key == ctx.period_start.strftime("%Y-%m")

    async def test_paid_tenant_uses_subscription_period(self, db):
        await _seed(db, tenant_id="paid-t", tier="starter", subscription=True)
        ctx = await _resolver().resolve("paid-t")
        assert ctx.tier == "starter"
        assert ctx.included == 1_000_000
        # sqlite drops tzinfo (postgres preserves it); assert on the date/key
        assert ctx.period_start.date() == datetime(2026, 3, 15).date()
        assert ctx.period_key == "2026-03-15"

    async def test_manual_enterprise_without_subscription_not_capped(self, db):
        # enterprise tenant provisioned by tier only (no stripe row) must resolve
        # to enterprise/unlimited, never free — the key hybrid guarantee.
        await _seed(db, tenant_id="ent-t", tier="enterprise")
        ctx = await _resolver().resolve("ent-t")
        assert ctx.tier == "enterprise"
        assert ctx.included == -1

    async def test_tier_comes_from_the_tenant_not_the_subscription(self, db):
        """the subscription supplies the period; the tenant supplies the tier."""
        await _seed(
            db,
            tenant_id="s-t",
            tier="enterprise",
            subscription=True,
            subscription_tier="starter",
        )
        ctx = await _resolver().resolve("s-t")
        assert ctx.tier == "enterprise"
        assert ctx.included == -1
        assert ctx.period_key == "2026-03-15"

    async def test_unknown_tenant_resolves_to_free(self, db):
        ctx = await _resolver().resolve("nobody")
        assert ctx.tier == "free"
        assert ctx.included == 100_000

    async def test_unknown_tenant_defaults_to_free(self, db):
        ctx = await _resolver().resolve("ghost")
        assert ctx.tier == "free"
        assert ctx.included == 100_000

    async def test_second_resolve_served_from_cache(self, db, monkeypatch):
        await _seed(db, tenant_id="cache-t", tier="free")
        resolver = _resolver()
        first = await resolver.resolve("cache-t")

        # after caching, a reload must not touch the db again
        async def _boom(*_a, **_k):
            raise AssertionError("resolver hit the db on a cached tenant")

        monkeypatch.setattr(resolver, "_load", _boom)
        second = await resolver.resolve("cache-t")
        assert second == first

    async def test_invalidate_forces_reload(self, db):
        await _seed(db, tenant_id="inv-t", tier="free")
        resolver = _resolver()
        await resolver.resolve("inv-t")
        resolver.invalidate("inv-t")
        # no exception → reload path works after invalidation
        ctx = await resolver.resolve("inv-t")
        assert ctx.tier == "free"
