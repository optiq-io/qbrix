from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from datetime import timedelta

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import GitHubApp
from qbrixstore.postgres.models import GitHubDelivery
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import Mention
from qbrixstore.postgres.models import Tenant

from proxysvc.core.cursor import Position
from proxysvc.mod.change.proposal import HAPPENED
from proxysvc.mod.github.mention import MERGED
from proxysvc.mod.github.mention import PULL_REQUEST

DELIVERIES_KEPT = timedelta(days=7)


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


class MentionRepository:
    """the workspace's mentions, and the loops their keys name."""

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    async def resolve_keys(self, keys: Collection[str]) -> dict[str, str]:
        """each key's loop: the one with that key now, else the newest loop
        that had it as a draft key before a rename. a key no loop ever had
        resolves to nothing."""
        if not keys:
            return {}
        stmt = select(Loop.key, Loop.id).where(
            Loop.tenant_id == self._tenant_id, Loop.key.in_(keys)
        )
        found = dict((await self._session.execute(stmt)).all())
        earlier = [key for key in keys if key not in found]
        if not earlier:
            return found
        before_key = Change.before["key"].as_string()
        stmt = (
            select(before_key, Change.target_id)
            .join(
                Loop,
                and_(Loop.id == Change.target_id, Loop.tenant_id == self._tenant_id),
            )
            .where(
                Change.tenant_id == self._tenant_id,
                Change.kind == "loop.rename",
                Change.target_type == "loop",
                Change.status.in_(HAPPENED),
                before_key.in_(earlier),
            )
            .order_by(Change.created_at.desc(), Change.id.desc())
        )
        for key, loop_id in (await self._session.execute(stmt)).all():
            found.setdefault(key, loop_id)
        return found

    async def for_ref(self, repository: str, kind: str, ref: str) -> list[Mention]:
        """every loop's entry for one pull request or commit."""
        stmt = select(Mention).where(
            Mention.tenant_id == self._tenant_id,
            Mention.repository == repository,
            Mention.kind == kind,
            Mention.ref == ref,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    def add(self, mention: Mention) -> None:
        self._session.add(mention)

    async def page_for(
        self, loop_id: str, before: Position | None, limit: int
    ) -> list[Mention]:
        """a loop's mentions newest first, from just after before."""
        stmt = select(Mention).where(
            Mention.tenant_id == self._tenant_id, Mention.loop_id == loop_id
        )
        if before is not None:
            at, mention_id = before
            stmt = stmt.where(
                or_(
                    Mention.at < at,
                    and_(Mention.at == at, Mention.id < mention_id),
                )
            )
        stmt = stmt.order_by(Mention.at.desc(), Mention.id.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    def _merged(self):
        return select(Mention).where(
            Mention.tenant_id == self._tenant_id,
            Mention.kind == PULL_REQUEST,
            Mention.state == MERGED,
        )

    async def latest_merged(self, loop_id: str) -> Mention | None:
        """the loop's most recently merged pull request."""
        stmt = (
            self._merged()
            .where(Mention.loop_id == loop_id)
            .order_by(Mention.merged_at.desc(), Mention.id.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def merged_drafts(self, owner_user_id: str) -> list[tuple[Loop, Mention]]:
        """each of a person's drafts that a merged pull request mentions, with
        the latest such pull request, newest first."""
        stmt = (
            self._merged()
            .add_columns(Loop)
            .join(
                Loop,
                and_(
                    Loop.id == Mention.loop_id,
                    Loop.tenant_id == self._tenant_id,
                    Loop.state == "draft",
                    Loop.owner_user_id == owner_user_id,
                ),
            )
            .order_by(Mention.merged_at.desc(), Mention.id.desc())
        )
        latest: dict[str, tuple[Loop, Mention]] = {}
        for mention, loop in (await self._session.execute(stmt)).all():
            latest.setdefault(loop.id, (loop, mention))
        return list(latest.values())

    async def counts_by_repository(self) -> dict[str, tuple[int, datetime]]:
        """how many entries each repository has, and the latest one's time."""
        stmt = (
            select(Mention.repository, func.count(), func.max(Mention.at))
            .where(Mention.tenant_id == self._tenant_id)
            .group_by(Mention.repository)
        )
        return {
            repository: (count, last)
            for repository, count, last in (await self._session.execute(stmt)).all()
        }


async def first_delivery(
    session: AsyncSession, tenant_id: str, delivery_id: str, *, now: datetime
) -> bool:
    """record a delivery, and say whether it is the first time it arrived.
    deliveries older than a week are forgotten; github redelivers within days."""
    await session.execute(
        delete(GitHubDelivery).where(GitHubDelivery.received_at < now - DELIVERIES_KEPT)
    )
    if await session.get(GitHubDelivery, delivery_id) is not None:
        return False
    try:
        async with session.begin_nested():
            session.add(
                GitHubDelivery(id=delivery_id, tenant_id=tenant_id, received_at=now)
            )
    except IntegrityError:
        return False
    return True
