"""a lease one holder at a time takes, renews and gives up."""

from __future__ import annotations

import pytest

from qbrixstore.redis.client import RedisClient

pytestmark = pytest.mark.integration

LEASE = "safety"
KEY = f"qbrix:lease:{LEASE}"
TTL_MS = 60_000


@pytest.fixture
async def store(redis_server) -> RedisClient:
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


async def test_the_first_holder_takes_it_with_its_ttl(store):
    assert await store.acquire_lease(LEASE, "a", TTL_MS)

    assert await store.client.get(KEY) == "a"
    assert 0 < await store.client.pttl(KEY) <= TTL_MS


async def test_another_holder_is_refused(store):
    await store.acquire_lease(LEASE, "a", TTL_MS)

    assert not await store.acquire_lease(LEASE, "b", TTL_MS)
    assert await store.client.get(KEY) == "a"


async def test_the_holder_renews_it(store):
    await store.acquire_lease(LEASE, "a", TTL_MS)
    await store.client.pexpire(KEY, 1_000)

    assert await store.acquire_lease(LEASE, "a", TTL_MS)
    assert await store.client.pttl(KEY) > 1_000


async def test_once_it_lapses_another_holder_takes_it(store):
    await store.acquire_lease(LEASE, "a", TTL_MS)
    await store.client.delete(KEY)

    assert await store.acquire_lease(LEASE, "b", TTL_MS)
    assert not await store.acquire_lease(LEASE, "a", TTL_MS)


async def test_only_the_holder_releases_it(store):
    await store.acquire_lease(LEASE, "a", TTL_MS)

    await store.release_lease(LEASE, "b")
    assert await store.client.get(KEY) == "a"

    await store.release_lease(LEASE, "a")
    assert await store.client.get(KEY) is None
