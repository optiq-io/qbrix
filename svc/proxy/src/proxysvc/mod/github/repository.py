from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import GitHubApp
from qbrixstore.postgres.models import Tenant


class GitHubAppRepository:

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def get(self) -> GitHubApp | None:
        stmt = select(GitHubApp).where(GitHubApp.tenant_id == self._tenant_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    def add(self, app: GitHubApp) -> None:
        self._session.add(app)

    async def delete(self) -> None:
        await self._session.execute(
            delete(GitHubApp).where(GitHubApp.tenant_id == self._tenant_id)
        )

    async def workspace_slug(self) -> str:
        stmt = select(Tenant.slug).where(Tenant.id == self._tenant_id)
        return (await self._session.execute(stmt)).scalar_one()


async def by_events_token(session: AsyncSession, token: str) -> GitHubApp | None:
    """the app whose events arrive at this token's address, in any workspace."""
    stmt = select(GitHubApp).where(GitHubApp.events_token == token)
    return (await session.execute(stmt)).scalar_one_or_none()
