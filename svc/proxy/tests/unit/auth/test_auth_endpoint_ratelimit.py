from __future__ import annotations

from typing import Any, AsyncGenerator

import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from qbrixstore.redis.client import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.mod.auth.service import AuthService
from proxysvc import edition
from proxysvc.core.email import EmailService

from svc.proxy.tests.conftest import RecordingSender


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[FakeRedis, Any]:
    client = FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


def _make_service(fake_redis: FakeRedis) -> AuthService:
    redis_client = RedisClient()
    redis_client._client = fake_redis
    return AuthService(
        redis_client,
        EmailService(RecordingSender()),
        edition.entitlements(ProxySettings(), redis_client),
    )


class TestAuthEndpointRateLimit:

    async def test_allows_up_to_limit_then_blocks(self, fake_redis):
        svc = _make_service(fake_redis)

        # limit=3: first three allowed, fourth blocked
        for _ in range(3):
            allowed, retry_after = await svc.check_auth_endpoint_rate_limit(
                "login", "1.2.3.4", 3
            )
            assert allowed is True

        allowed, retry_after = await svc.check_auth_endpoint_rate_limit(
            "login", "1.2.3.4", 3
        )
        assert allowed is False
        assert 1 <= retry_after <= 60

    async def test_zero_or_negative_limit_is_disabled(self, fake_redis):
        svc = _make_service(fake_redis)
        for limit in (0, -1):
            allowed, retry_after = await svc.check_auth_endpoint_rate_limit(
                "login", "1.2.3.4", limit
            )
            assert allowed is True
            assert retry_after == 0

    async def test_distinct_identifiers_are_independent(self, fake_redis):
        svc = _make_service(fake_redis)

        # exhaust ip A
        for _ in range(2):
            await svc.check_auth_endpoint_rate_limit("login", "1.1.1.1", 2)
        a_allowed, _ = await svc.check_auth_endpoint_rate_limit("login", "1.1.1.1", 2)
        assert a_allowed is False

        # ip B is unaffected
        b_allowed, _ = await svc.check_auth_endpoint_rate_limit("login", "2.2.2.2", 2)
        assert b_allowed is True

    async def test_distinct_scopes_are_independent(self, fake_redis):
        svc = _make_service(fake_redis)

        for _ in range(2):
            await svc.check_auth_endpoint_rate_limit("login", "1.1.1.1", 2)
        login_allowed, _ = await svc.check_auth_endpoint_rate_limit(
            "login", "1.1.1.1", 2
        )
        assert login_allowed is False

        # same identifier, different scope → separate bucket
        forgot_allowed, _ = await svc.check_auth_endpoint_rate_limit(
            "forgot", "1.1.1.1", 2
        )
        assert forgot_allowed is True

    async def test_limit_enforced_across_replicas(self, fake_redis):
        """two service instances sharing one redis enforce a single limit.

        simulates horizontally-scaled proxy pods: the count must be shared.
        """
        svc_a = _make_service(fake_redis)
        svc_b = _make_service(fake_redis)

        # two requests hit replica A
        for _ in range(2):
            allowed, _ = await svc_a.check_auth_endpoint_rate_limit(
                "login", "9.9.9.9", 3
            )
            assert allowed is True

        # third request lands on replica B — still allowed (3rd overall)
        allowed, _ = await svc_b.check_auth_endpoint_rate_limit("login", "9.9.9.9", 3)
        assert allowed is True

        # fourth request on replica B exceeds the shared limit
        allowed, retry_after = await svc_b.check_auth_endpoint_rate_limit(
            "login", "9.9.9.9", 3
        )
        assert allowed is False
        assert retry_after >= 1
