from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import User

FORMER_MEMBER = "former member"


class People:
    """the names of the people one response mentions, read in one query.

    ids are kept without a foreign key wherever history must outlive a user, so
    a missing user is a former member, never an error.
    """

    def __init__(self, names: Mapping[str, str]):
        self._names = dict(names)

    @classmethod
    async def load(
        cls, session: AsyncSession, tenant_id: str, user_ids: Iterable[str]
    ) -> People:
        ids = {user_id for user_id in user_ids if user_id}
        if not ids:
            return cls({})
        stmt = select(User.id, User.name, User.email).where(
            User.tenant_id == tenant_id, User.id.in_(ids)
        )
        rows = (await session.execute(stmt)).all()
        return cls({row.id: row.name or row.email for row in rows})

    def name(self, user_id: str) -> str:
        return self._names.get(user_id, FORMER_MEMBER)
