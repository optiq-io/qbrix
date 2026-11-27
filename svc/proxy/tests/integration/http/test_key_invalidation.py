"""a revoked or rotated-out key must be refused on every replica at once.

each proxy replica caches a validated key by its hash for a minute, and the
replica that serves the revoke is rarely the one serving the app's next call.
these tests run two replicas, each with its own key cache and its own
subscription, over one redis, and assert the other replica refuses the old
secret within a second.
"""

from __future__ import annotations

import asyncio
import time

import fakeredis
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

import qbrixstore.postgres.session as _session_module
import qbrixstore.redis.pubsub as _pubsub_module
from qbrixstore.config import RedisSettings
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User
from qbrixstore.redis.client import RedisClient

from proxysvc.core.actor import Actor
from proxysvc.core.email import EmailService
from proxysvc.core.invalidation import KeyInvalidation
from proxysvc.mod.auth.service import AuthService
from proxysvc.mod.key.service import KeyService

from svc.proxy.tests.conftest import RecordingSender

TENANT_ID = "tenant-a"
ADMIN_ID = "user-admin"
WITHIN_SEC = 1.0


class _Unlimited:
    def limits(self, tier: str) -> dict[str, int]:
        return {"max_api_keys": -1}


class _Silent:
    async def publish(self, key_hash: str, /) -> None:
        return None


class _Replica:
    """one proxy process: its own key cache and its own subscription."""

    def __init__(self, redis: RedisClient):
        self.auth = AuthService(redis, EmailService(RecordingSender()), _Unlimited())
        self.bus = KeyInvalidation(RedisSettings())
        self.bus.register(self.auth.evict_api_key)
        self.keys = KeyService(entitlements=_Unlimited(), announcer=self.bus)

    async def accepts(self, secret: str) -> bool:
        return await self.auth.validate_api_key(secret) is not None


async def _refused_within(replica: _Replica, secret: str) -> bool:
    deadline = time.monotonic() + WITHIN_SEC
    while time.monotonic() < deadline:
        if not await replica.accepts(secret):
            return True
        await asyncio.sleep(0.02)
    return False


@pytest_asyncio.fixture
async def redis_server(monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        _pubsub_module.redis,
        "from_url",
        lambda *_a, **_k: FakeRedis(server=server, decode_responses=True),
    )
    return server


@pytest_asyncio.fixture
async def replicas(app_with_db, redis_server):
    client = RedisClient()
    client._client = FakeRedis(server=redis_server, decode_responses=True)
    async with _session_module.get_session() as session:
        session.add(Tenant(id=TENANT_ID, name=TENANT_ID, slug=TENANT_ID))
        session.add(
            User(
                id=ADMIN_ID,
                tenant_id=TENANT_ID,
                email="admin@example.com",
                password_hash="x",
                role="admin",
            )
        )
    a, b = _Replica(client), _Replica(client)
    await a.bus.start()
    await b.bus.start()
    await asyncio.sleep(0.1)
    yield a, b
    await a.bus.stop()
    await b.bus.stop()
    await client._client.aclose()


async def _cached_on_both(a: _Replica, b: _Replica) -> dict:
    created = await a.keys.create(
        TENANT_ID, app="shop", environment="production", actor=Actor.member(ADMIN_ID)
    )
    assert await a.accepts(created["secret"])
    assert await b.accepts(created["secret"])
    assert b.auth._api_key_cache
    return created


class TestCrossReplicaRefusal:
    async def test_a_revoked_key_is_refused_on_the_other_replica(self, replicas):
        a, b = replicas
        created = await _cached_on_both(a, b)

        await a.keys.revoke(TENANT_ID, created["id"])

        assert not await a.accepts(created["secret"])
        assert await _refused_within(b, created["secret"])

    async def test_a_rotated_out_secret_is_refused_on_the_other_replica(self, replicas):
        a, b = replicas
        created = await _cached_on_both(a, b)

        rotated = await a.keys.rotate(TENANT_ID, created["id"])

        assert not await a.accepts(created["secret"])
        assert await _refused_within(b, created["secret"])
        assert await b.accepts(rotated["secret"])

    async def test_without_the_announcement_the_other_replica_stays_stale(
        self, replicas
    ):
        """the control: the refusal above comes from the broadcast, not from a
        cache miss."""
        a, b = replicas
        created = await _cached_on_both(a, b)
        a.keys._announcer = _Silent()

        await a.keys.revoke(TENANT_ID, created["id"])
        await asyncio.sleep(0.1)

        assert await b.accepts(created["secret"])
