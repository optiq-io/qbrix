"""unit tests for the tenant-scoped count queries backing plan-limit checks."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

from qbrixstore.postgres.models import APIKey
from qbrixstore.postgres.models import Base
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User

from proxysvc.mod.auth.repository import APIKeyRepository
from proxysvc.mod.auth.repository import TenantRepository
from proxysvc.mod.auth.repository import UserRepository


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed_member(session, *, tenant_id: str, user_id: str, keys: list[bool]):
    """add a user to a tenant with one key per entry in keys (True = active)."""
    session.add(
        User(
            id=user_id,
            tenant_id=tenant_id,
            email=f"{user_id}@example.com",
            password_hash="x",
        )
    )
    for index, is_active in enumerate(keys):
        session.add(
            APIKey(
                id=f"{user_id}-k{index}",
                user_id=user_id,
                key_hash=f"{user_id}-hash-{index}",
                is_active=is_active,
            )
        )


@pytest_asyncio.fixture
async def seeded(session_factory):
    async with session_factory() as session:
        session.add(Tenant(id="t-1", name="Acme", slug="acme"))
        session.add(Tenant(id="t-2", name="Other", slug="other"))
        await _seed_member(session, tenant_id="t-1", user_id="u-1", keys=[True, True])
        await _seed_member(session, tenant_id="t-1", user_id="u-2", keys=[True, False])
        await _seed_member(session, tenant_id="t-2", user_id="u-3", keys=[True, True])
        await session.commit()
    return session_factory


class TestUserCountByTenant:

    @pytest.mark.asyncio
    async def test_counts_only_the_given_tenant(self, seeded):
        async with seeded() as session:
            repo = UserRepository(session)
            assert await repo.count_by_tenant("t-1") == 2
            assert await repo.count_by_tenant("t-2") == 1

    @pytest.mark.asyncio
    async def test_unknown_tenant_is_zero(self, seeded):
        async with seeded() as session:
            assert await UserRepository(session).count_by_tenant("t-missing") == 0


class TestAPIKeyCountByTenant:

    @pytest.mark.asyncio
    async def test_sums_active_keys_across_members(self, seeded):
        """u-1 holds 2 active, u-2 holds 1 active + 1 revoked."""
        async with seeded() as session:
            assert await APIKeyRepository(session).count_by_tenant("t-1") == 3

    @pytest.mark.asyncio
    async def test_excludes_other_tenants(self, seeded):
        async with seeded() as session:
            assert await APIKeyRepository(session).count_by_tenant("t-2") == 2

    @pytest.mark.asyncio
    async def test_revoking_frees_a_slot(self, seeded):
        async with seeded() as session:
            repo = APIKeyRepository(session)
            await repo.deactivate("u-1-k0")
            assert await repo.count_by_tenant("t-1") == 2

    @pytest.mark.asyncio
    async def test_tenant_without_keys_is_zero(self, seeded):
        async with seeded() as session:
            session.add(Tenant(id="t-3", name="Empty", slug="empty"))
            await _seed_member(session, tenant_id="t-3", user_id="u-4", keys=[])
            await session.flush()
            assert await APIKeyRepository(session).count_by_tenant("t-3") == 0


class TestUserCarriesItsTenant:
    """the tier is read off user.tenant, so every user load must carry it."""

    @pytest.mark.asyncio
    async def test_get_loads_the_tenant(self, seeded):
        async with seeded() as session:
            user = await UserRepository(session).get("u-1")
            assert user.tenant.id == "t-1"

    @pytest.mark.asyncio
    async def test_get_by_email_loads_the_tenant(self, seeded):
        async with seeded() as session:
            user = await UserRepository(session).get_by_email("u-1@example.com")
            assert user.tenant.id == "t-1"

    @pytest.mark.asyncio
    async def test_create_loads_the_tenant(self, seeded):
        async with seeded() as session:
            user = await UserRepository(session).create(
                email="new@example.com", password_hash="x", tenant_id="t-1"
            )
            assert user.tenant.id == "t-1"

    @pytest.mark.asyncio
    async def test_list_by_tenant_loads_the_tenant(self, seeded):
        async with seeded() as session:
            users = await UserRepository(session).list_by_tenant("t-1")
            assert users and all(u.tenant.id == "t-1" for u in users)

    @pytest.mark.asyncio
    async def test_a_loaded_user_carries_the_tenant_tier(self, seeded):
        """callers read the tier off the user, so the joined tenant must carry it."""
        async with seeded() as session:
            await TenantRepository(session).update_plan_tier("t-1", "growth")
            await session.commit()

        async with seeded() as session:
            user = await UserRepository(session).get("u-1")
            assert user.tenant.plan_tier == "growth"


class TestTenantUpdatePlanTier:

    @pytest.mark.asyncio
    async def test_defaults_to_free(self, seeded):
        async with seeded() as session:
            tenant = await TenantRepository(session).get("t-1")
            assert tenant.plan_tier == "free"

    @pytest.mark.asyncio
    async def test_updates_only_the_target_tenant(self, seeded):
        async with seeded() as session:
            repo = TenantRepository(session)
            await repo.update_plan_tier("t-1", "growth")
            await session.commit()

        async with seeded() as session:
            repo = TenantRepository(session)
            assert (await repo.get("t-1")).plan_tier == "growth"
            assert (await repo.get("t-2")).plan_tier == "free"

    @pytest.mark.asyncio
    async def test_unknown_tenant_is_a_noop(self, seeded):
        async with seeded() as session:
            await TenantRepository(session).update_plan_tier("t-missing", "enterprise")
            await session.commit()

        async with seeded() as session:
            assert (await TenantRepository(session).get("t-1")).plan_tier == "free"
