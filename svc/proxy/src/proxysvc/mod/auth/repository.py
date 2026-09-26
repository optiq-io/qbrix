from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import List

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload

from qbrixstore.postgres.models import APIKey
from qbrixstore.postgres.models import Invite
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User

# every user load carries its tenant, because the tenant owns the plan tier and
# callers read it off the user. joinedload keeps it in the same query, so the
# authenticated request path costs no extra round trip.
_USER_LOADS = (selectinload(User.api_keys), joinedload(User.tenant))


class TenantRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, name: str, slug: str) -> Tenant:
        """
        Create a tenant for the given name and slug in the database.
        Parameters
        ----------
        name: string
            tenant name
        slug: string
            tenant slug

        Returns
        -------
            Tenant object
        """
        tenant = Tenant(name=name, slug=slug)
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def get(self, tenant_id: str) -> Tenant | None:
        """
        Get a tenant for the given tenant_id from the database.
        Parameters
        ----------
        tenant_id: string

        Returns
        -------
        Tenant object
        """
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Tenant | None:
        """
        Get a tenant for the given slug from the database.

        Parameters
        ----------
        slug: string

        Returns
        -------
        Tenant object
        """
        stmt = select(Tenant).where(Tenant.slug == slug)
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def list(self, limit: int = 100, offset: int = 0) -> list[Tenant]:
        """
        List all the tenants in the database.
        Parameters
        ----------
        limit: int
            default: 1000
        offset: int
            default: 0

        Returns
        -------
        List of Tenant objects
        """
        stmt = (
            select(Tenant)
            .where(Tenant.is_active == True)
            .order_by(Tenant.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        response = await self._session.execute(stmt)
        return list(response.scalars().all())

    async def update(self, tenant_id: str, **kwargs) -> Tenant | None:
        """
        Update a tenant for the given tenant_id in the database.

        Parameters
        ----------
        tenant_id: string
        **kwargs: fields to update

        Returns
        -------
        Tenant object or None
        """
        tenant = await self.get(tenant_id)
        if tenant is None:
            return None

        for key, value in kwargs.items():
            if hasattr(tenant, key) and value is not None:
                setattr(tenant, key, value)

        await self._session.flush()
        return tenant

    async def update_plan_tier(self, tenant_id: str, plan_tier: str) -> None:
        """
        Set the tenant's entitlement tier.

        Written only by the billing reconciliation path, in the same transaction
        as the subscriptions row it is derived from.

        Parameters
        ----------
        tenant_id: string
        plan_tier: string
        """
        await self._session.execute(
            update(Tenant).where(Tenant.id == tenant_id).values(plan_tier=plan_tier)
        )

    async def deactivate(self, tenant_id: str) -> bool:
        """
        Deactivate a tenant for the given tenant_id from the database.

        Parameters
        ----------
        tenant_id: string

        Returns
        -------
        Bool
        """
        tenant = await self.get(tenant_id)
        if tenant is None:
            return False
        tenant.is_active = False
        await self._session.flush()
        return True


class UserRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        email: str,
        password_hash: str,
        tenant_id: str,
        name: str | None = None,
        role: str = "member",
        email_verified: bool = False,
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            tenant_id=tenant_id,
            name=name,
            role=role,
            email_verified=email_verified,
            email_verified_at=(datetime.now(timezone.utc) if email_verified else None),
        )
        self._session.add(user)
        await self._session.flush()
        # return through the standard loader so a created user carries its
        # tenant exactly like a fetched one; callers read the tier off it.
        return await self.get(user.id)

    async def get(self, user_id: str) -> User | None:
        stmt = select(User).options(*_USER_LOADS).where(User.id == user_id)
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).options(*_USER_LOADS).where(User.email == email)
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def update(self, user_id: str, **kwargs) -> User | None:
        user = await self.get(user_id)
        if user is None:
            return None

        for key, value in kwargs.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)

        await self._session.flush()
        return user

    async def deactivate(self, user_id: str) -> bool:
        user = await self.get(user_id)
        if user is None:
            return False
        user.is_active = False
        await self._session.flush()
        return True

    async def delete(self, user_id: str) -> bool:
        user = await self.get(user_id)
        if user is None:
            return False
        await self._session.delete(user)
        await self._session.flush()
        return True

    async def list(self, limit: int = 100, offset: int = 0) -> list[User]:
        stmt = (
            select(User)
            .options(*_USER_LOADS)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        response = await self._session.execute(stmt)
        return list(response.scalars().all())

    async def list_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> List[User]:
        stmt = (
            select(User)
            .options(*_USER_LOADS)
            .where(User.tenant_id == tenant_id)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        response = await self._session.execute(stmt)
        return list(response.scalars().all())

    async def count_by_tenant(self, tenant_id: str) -> int:
        stmt = select(func.count(User.id)).where(User.tenant_id == tenant_id)
        response = await self._session.execute(stmt)
        return response.scalar_one()

    async def any_exists(self) -> bool:
        stmt = select(User.id).limit(1)
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none() is not None

    async def count_by_role(self, tenant_id: str) -> dict[str, int]:
        stmt = (
            select(User.role, func.count(User.id))
            .where(User.tenant_id == tenant_id)
            .group_by(User.role)
        )
        response = await self._session.execute(stmt)
        result = {role: count for role, count in response.all()}

        for role in ["admin", "member", "viewer"]:
            if role not in result:
                result[role] = 0

        return result

    async def search(
        self,
        tenant_id: str,
        query: str | None = None,
        role: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[User]:
        stmt = select(User).options(*_USER_LOADS).where(User.tenant_id == tenant_id)

        if query:
            search_pattern = f"%{query}%"
            stmt = stmt.where(
                (User.email.ilike(search_pattern)) | (User.name.ilike(search_pattern))
            )

        if role:
            stmt = stmt.where(User.role == role)

        if status:
            is_active = status.lower() == "active"
            stmt = stmt.where(User.is_active == is_active)

        stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
        response = await self._session.execute(stmt)
        return list(response.scalars().all())


class APIKeyRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        user_id: str,
        key_hash: str,
        name: str = "Default API Key",
        rate_limit_per_minute: int = 1000,
        scopes: list[str] | None = None,
    ) -> APIKey:
        api_key = APIKey(
            user_id=user_id,
            key_hash=key_hash,
            name=name,
            rate_limit_per_minute=rate_limit_per_minute,
            scopes=scopes or [],
        )
        self._session.add(api_key)
        await self._session.flush()
        return api_key

    async def get(self, api_key_id: str) -> APIKey | None:
        stmt = (
            select(APIKey)
            .options(selectinload(APIKey.user))
            .where(APIKey.id == api_key_id)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def get_by_hash(self, key_hash: str) -> APIKey | None:
        stmt = (
            select(APIKey)
            .options(selectinload(APIKey.user))
            .where(APIKey.key_hash == key_hash)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> list[APIKey]:
        stmt = (
            select(APIKey)
            .where(APIKey.user_id == user_id, APIKey.is_active == True)
            .order_by(APIKey.created_at.desc())
        )
        response = await self._session.execute(stmt)
        return list(response.scalars().all())

    async def count_by_tenant(self, tenant_id: str) -> int:
        """count active keys across every member of a tenant."""
        stmt = (
            select(func.count(APIKey.id))
            .join(User, APIKey.user_id == User.id)
            .where(User.tenant_id == tenant_id, APIKey.is_active == True)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one()

    async def update(self, api_key_id: str, **kwargs) -> APIKey | None:
        api_key = await self.get(api_key_id)
        if api_key is None:
            return None

        for key, value in kwargs.items():
            if hasattr(api_key, key) and value is not None:
                setattr(api_key, key, value)

        await self._session.flush()
        return api_key

    async def update_last_used(self, api_key_id: str) -> bool:
        api_key = await self.get(api_key_id)
        if api_key is None:
            return False
        api_key.last_used_at = datetime.now(timezone.utc)
        await self._session.flush()
        return True

    async def deactivate(self, api_key_id: str) -> bool:
        api_key = await self.get(api_key_id)
        if api_key is None:
            return False
        api_key.is_active = False
        await self._session.flush()
        return True

    async def delete(self, api_key_id: str) -> bool:
        api_key = await self.get(api_key_id)
        if api_key is None:
            return False
        await self._session.delete(api_key)
        await self._session.flush()
        return True


class InviteRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        tenant_id: str,
        email: str,
        role: str,
        token: str,
        invited_by: str,
        expires_at: datetime,
    ) -> Invite:
        invite = Invite(
            tenant_id=tenant_id,
            email=email,
            role=role,
            token=token,
            invited_by=invited_by,
            expires_at=expires_at,
        )
        self._session.add(invite)
        await self._session.flush()
        return invite

    async def get_by_token(self, token: str) -> Invite | None:
        stmt = (
            select(Invite)
            .options(selectinload(Invite.tenant))
            .where(Invite.token == token)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_tenant(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Invite]:
        stmt = select(Invite).where(Invite.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Invite.status == status)
        stmt = stmt.order_by(Invite.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(self, invite_id: str, status: str) -> Invite | None:
        stmt = select(Invite).where(Invite.id == invite_id)
        result = await self._session.execute(stmt)
        invite = result.scalar_one_or_none()
        if invite is None:
            return None
        invite.status = status
        await self._session.flush()
        return invite

    async def get_pending_by_email_and_tenant(
        self, email: str, tenant_id: str
    ) -> Invite | None:
        stmt = select(Invite).where(
            Invite.email == email,
            Invite.tenant_id == tenant_id,
            Invite.status == "pending",
            Invite.expires_at >= datetime.now(timezone.utc),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_pending_by_tenant(self, tenant_id: str) -> int:
        stmt = select(func.count(Invite.id)).where(
            Invite.tenant_id == tenant_id,
            Invite.status == "pending",
            Invite.expires_at >= datetime.now(timezone.utc),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
