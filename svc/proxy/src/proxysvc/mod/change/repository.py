from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Change

from proxysvc.core.actor import Actor


class ChangeRepository:
    """the change log. a write records its change on the session it writes
    with, so the object and its record commit together or not at all."""

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def record(
        self,
        kind: str,
        target_type: str,
        target_id: str,
        actor: Actor,
        *,
        before: dict | None = None,
        after: dict | None = None,
        learning: dict | None = None,
        reason: str | None = None,
        evidence: dict | None = None,
    ) -> Change:
        change = Change(
            tenant_id=self._tenant_id,
            kind=kind,
            target_type=target_type,
            target_id=target_id,
            actor_kind=actor.kind,
            actor_user_id=actor.user_id,
            connection_id=actor.connection_id or None,
            client_name=actor.client_name or None,
            api_key_id=actor.api_key_id or None,
            request_id=actor.request_id or None,
            reason=reason,
            evidence=evidence,
            before=before,
            after=after,
            learning=learning,
        )
        self._session.add(change)
        await self._session.flush()
        return change

    async def get(self, change_id: str) -> Change | None:
        stmt = select(Change).where(
            Change.id == change_id, Change.tenant_id == self._tenant_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for(
        self, target_type: str, target_id: str, limit: int = 50
    ) -> list[Change]:
        stmt = (
            select(Change)
            .where(
                Change.tenant_id == self._tenant_id,
                Change.target_type == target_type,
                Change.target_id == target_id,
            )
            .order_by(Change.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
