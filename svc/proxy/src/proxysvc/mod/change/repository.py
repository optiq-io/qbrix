from __future__ import annotations

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Change

from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.mod.change.undo import Undoing


def later_change_message(later: Change) -> str:
    return (
        f"a later change exists on this {later.target_type}: {later.kind} "
        f"({later.id}). undo that one first"
    )


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
        undoing: Undoing | None = None,
    ) -> Change:
        if undoing is not None:
            await self._mark_undone(undoing, target_type, target_id)
            reason = undoing.reason
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
            undoes_id=undoing.change_id if undoing else None,
        )
        self._session.add(change)
        await self._session.flush()
        return change

    async def _mark_undone(
        self, undoing: Undoing, target_type: str, target_id: str
    ) -> None:
        """inside the undo's transaction, so a change that lands after the
        undo was checked, or a concurrent undo, still refuses it."""
        latest = await self.latest_for(target_type, target_id)
        if latest is not None and latest.id != undoing.latest_id:
            raise ChangeConflictError(later_change_message(latest))
        change_id = undoing.change_id
        result = await self._session.execute(
            update(Change)
            .where(
                Change.id == change_id,
                Change.tenant_id == self._tenant_id,
                Change.status == "applied",
            )
            .values(status="undone")
        )
        if result.rowcount != 1:
            raise ChangeConflictError(f"change {change_id} was already undone")

    async def latest_for(self, target_type: str, target_id: str) -> Change | None:
        changes = await self.list_for(target_type, target_id, limit=1)
        return changes[0] if changes else None

    async def list_after(self, change: Change) -> list[Change]:
        """later changes to the same target, newest first."""
        stmt = (
            select(Change)
            .where(
                Change.tenant_id == self._tenant_id,
                Change.target_type == change.target_type,
                Change.target_id == change.target_id,
                Change.created_at > change.created_at,
            )
            .order_by(Change.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def undone_by(self, change_id: str) -> Change | None:
        stmt = select(Change).where(
            Change.undoes_id == change_id, Change.tenant_id == self._tenant_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

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
