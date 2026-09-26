"""a tier change on one replica must be visible on every other replica.

the proxy runs behind an HPA, so the replica that serves the stripe webhook is
almost never the one serving the customer's next request. these tests run two
independently-cached AuthService/PlanEntitlements pairs over one redis — the
shape of two pods — and assert the second one stops serving the old tier.
"""

from __future__ import annotations

import asyncio

import fakeredis
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

import qbrixstore.postgres.session as _session_module
import qbrixstore.redis.pubsub as _pubsub_module
from qbrixstore.config import RedisSettings
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User
from qbrixstore.redis.client import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.email import EmailService
from proxysvc.core.invalidation import TenantInvalidation
from proxysvc.mod.auth.service import AuthService
from proxysvc import edition

from svc.proxy.tests.conftest import RecordingSender

TENANT_ID = "tenant-a"


class _Replica:
    """one proxy process: its own principal cache, its own tier cache, its own
    subscription to the shared invalidation channel."""

    def __init__(self, redis: RedisClient):
        self.entitlements = edition.entitlements(ProxySettings(), redis)
        self.auth = AuthService(
            redis, EmailService(RecordingSender()), self.entitlements
        )
        self.bus = TenantInvalidation(RedisSettings())
        self.bus.register(self.auth.invalidate_tenant)
        self.bus.register(self.entitlements.invalidate)

    async def start(self) -> None:
        await self.bus.start()

    async def stop(self) -> None:
        await self.bus.stop()

    async def tier_of(self, user_id: str) -> str:
        user = await self.auth.get_user(user_id)
        return user["plan_tier"]

    async def metered_tier(self) -> str:
        ctx = await self.entitlements._resolver.resolve(TENANT_ID)
        return ctx.tier


async def _seed(tier: str) -> str:
    async with _session_module.get_session() as session:
        session.add(
            Tenant(id=TENANT_ID, name=TENANT_ID, slug=TENANT_ID, plan_tier=tier)
        )
        await session.flush()
        user = User(
            tenant_id=TENANT_ID,
            email="member@example.com",
            password_hash="x",
        )
        session.add(user)
        await session.flush()
        return user.id


async def _write_tier(tier: str) -> None:
    """what the billing path commits before it announces."""
    async with _session_module.get_session() as session:
        tenant = await session.get(Tenant, TENANT_ID)
        tenant.plan_tier = tier


async def _settle() -> None:
    await asyncio.sleep(0.1)


@pytest_asyncio.fixture
async def redis_server(monkeypatch):
    """one shared fake redis; every bus connects with its own client on it."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        _pubsub_module.redis,
        "from_url",
        lambda *_a, **_k: FakeRedis(server=server, decode_responses=True),
    )
    return server


@pytest_asyncio.fixture
async def redis_client(redis_server):
    client = RedisClient()
    client._client = FakeRedis(server=redis_server, decode_responses=True)
    yield client
    await client._client.aclose()


@pytest_asyncio.fixture
async def replicas(redis_client):
    """two replicas sharing one redis, both already subscribed."""
    a, b = _Replica(redis_client), _Replica(redis_client)
    await a.start()
    await b.start()
    await _settle()
    yield a, b
    await a.stop()
    await b.stop()


class TestCrossReplicaVisibility:
    async def test_upgrade_reaches_the_replica_that_did_not_serve_it(
        self, app_with_db, replicas
    ):
        """the whole point in one assertion: the webhook lands on A, the customer's
        next request lands on B."""
        user_id = await _seed("free")
        a, b = replicas
        assert await a.tier_of(user_id) == "free"
        assert await b.tier_of(user_id) == "free"

        await _write_tier("growth")
        await a.bus.publish(TENANT_ID)
        await _settle()

        assert await a.tier_of(user_id) == "growth"
        assert await b.tier_of(user_id) == "growth"

    async def test_without_the_announcement_both_replicas_stay_stale(
        self, app_with_db, replicas
    ):
        """the control: proves the test above is measuring the invalidation and
        not some incidental cache miss."""
        user_id = await _seed("free")
        a, b = replicas
        await a.tier_of(user_id)
        await b.tier_of(user_id)

        await _write_tier("growth")
        await _settle()

        assert await a.tier_of(user_id) == "free"
        assert await b.tier_of(user_id) == "free"

    async def test_downgrade_reaches_the_other_replica(self, app_with_db, replicas):
        """entitlements have to be withdrawn as promptly as they are granted."""
        user_id = await _seed("growth")
        a, b = replicas
        assert await b.tier_of(user_id) == "growth"

        await _write_tier("free")
        await a.bus.publish(TENANT_ID)
        await _settle()

        assert await b.tier_of(user_id) == "free"

    async def test_selection_meter_tier_reaches_the_other_replica(
        self, app_with_db, replicas
    ):
        """the meter's cache is the one that rejects requests, so it has to move
        with the principal cache — a tenant blocked here has already paid."""
        await _seed("free")
        a, b = replicas
        assert await a.metered_tier() == "free"
        assert await b.metered_tier() == "free"

        await _write_tier("starter")
        await a.bus.publish(TENANT_ID)
        await _settle()

        assert await a.metered_tier() == "starter"
        assert await b.metered_tier() == "starter"

    async def test_other_tenants_keep_their_cached_principal(
        self, app_with_db, replicas
    ):
        """one tenant's billing event must not cost every other tenant a
        database read on the hot path."""
        user_id = await _seed("free")
        a, b = replicas
        await b.tier_of(user_id)

        await b.bus.publish("some-other-tenant")
        await _settle()

        assert b.auth._user_cache.get(user_id) is not None


class TestFeatureEntitlements:
    async def test_features_follow_the_tier_across_replicas(
        self, app_with_db, replicas
    ):
        """the console gates on `features`, not on the tier string, so the
        derived entitlements must move too."""
        from proxysvc.ee.plans import features_for

        user_id = await _seed("free")
        a, b = replicas
        assert features_for(await b.tier_of(user_id)) == []

        await _write_tier("scale")
        await a.bus.publish(TENANT_ID)
        await _settle()

        assert set(features_for(await b.tier_of(user_id))) == {
            "event_log",
            "insights",
            "rbac",
            "sso",
        }


@pytest.mark.parametrize("tier", ["starter", "growth", "scale", "enterprise"])
async def test_every_paid_tier_propagates(app_with_db, replicas, tier):
    user_id = await _seed("free")
    a, b = replicas

    await b.tier_of(user_id)
    await _write_tier(tier)
    await a.bus.publish(TENANT_ID)
    await _settle()

    assert await b.tier_of(user_id) == tier
