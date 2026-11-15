from __future__ import annotations

from collections.abc import Collection
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Alert


class AlertRepository:

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def open_for(self, loop_id: str, signal: str) -> Alert | None:
        stmt = select(Alert).where(
            Alert.tenant_id == self._tenant_id,
            Alert.loop_id == loop_id,
            Alert.signal == signal,
            Alert.resolved_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def open_on(
        self, loop_ids: Collection[str], signals: Collection[str] | None = None
    ) -> Sequence[Alert]:
        """the open alerts on these loops, oldest first."""
        if not loop_ids:
            return []
        stmt = select(Alert).where(
            Alert.tenant_id == self._tenant_id,
            Alert.loop_id.in_(loop_ids),
            Alert.resolved_at.is_(None),
        )
        if signals is not None:
            stmt = stmt.where(Alert.signal.in_(signals))
        stmt = stmt.order_by(Alert.opened_at, Alert.id)
        return (await self._session.execute(stmt)).scalars().all()

    async def list(
        self,
        *,
        loop_ids: Collection[str] | None,
        open: bool | None,
        limit: int,
    ) -> Sequence[Alert]:
        """the workspace's alerts, newest first."""
        stmt = select(Alert).where(Alert.tenant_id == self._tenant_id)
        if loop_ids is not None:
            stmt = stmt.where(Alert.loop_id.in_(loop_ids))
        if open is True:
            stmt = stmt.where(Alert.resolved_at.is_(None))
        elif open is False:
            stmt = stmt.where(Alert.resolved_at.is_not(None))
        stmt = stmt.order_by(Alert.opened_at.desc(), Alert.id.desc()).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()
