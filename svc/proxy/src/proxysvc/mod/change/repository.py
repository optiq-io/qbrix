from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Change

from proxysvc.core.actor import Actor
from proxysvc.core.cursor import Position
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeMovedError
from proxysvc.mod.change.undo import UNDOABLE_KINDS
from proxysvc.mod.change.undo import Undoing


def moved_since(later: Change) -> ChangeMovedError:
    return ChangeMovedError(
        f"a later change exists on this {later.target_type}: {later.kind} "
        f"({later.id}). undo that one first",
        later_change_id=later.id,
    )


def _older_than(before: Position):
    created_at, change_id = before
    return or_(
        Change.created_at < created_at,
        and_(Change.created_at == created_at, Change.id < change_id),
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
        """record one change against the object it is about.

        every change about a loop targets the loop, its cycles included, with
        the cycle in before and after: a loop's history is then one query.
        """
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
            raise moved_since(latest)
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

    async def page_for(
        self,
        target_type: str,
        target_id: str,
        before: Position | None,
        limit: int,
    ) -> list[Change]:
        """an object's changes newest first, from just after before."""
        stmt = select(Change).where(
            Change.tenant_id == self._tenant_id,
            Change.target_type == target_type,
            Change.target_id == target_id,
        )
        if before is not None:
            stmt = stmt.where(_older_than(before))
        stmt = stmt.order_by(Change.created_at.desc(), Change.id.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def page_workspace(
        self,
        before: Position | None,
        limit: int,
        *,
        actor_kinds: Collection[str] = (),
        kinds: Collection[str] = (),
        targets: Collection[tuple[str, str]] = (),
        undoable: bool | None = None,
    ) -> list[Change]:
        """the workspace's changes newest first, from just after before. every
        filter given narrows the page, targets included."""
        stmt = select(Change).where(Change.tenant_id == self._tenant_id)
        if before is not None:
            stmt = stmt.where(_older_than(before))
        if actor_kinds:
            stmt = stmt.where(Change.actor_kind.in_(actor_kinds))
        if kinds:
            stmt = stmt.where(Change.kind.in_(kinds))
        for target_type, target_id in targets:
            stmt = stmt.where(
                Change.target_type == target_type, Change.target_id == target_id
            )
        if undoable is not None:
            can_undo = and_(Change.kind.in_(UNDOABLE_KINDS), Change.status == "applied")
            stmt = stmt.where(can_undo if undoable else not_(can_undo))
        stmt = stmt.order_by(Change.created_at.desc(), Change.id.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def undone_by_each(self, change_ids: Collection[str]) -> dict[str, Change]:
        """the change that undid each of these, in one query."""
        if not change_ids:
            return {}
        stmt = select(Change).where(
            Change.tenant_id == self._tenant_id, Change.undoes_id.in_(change_ids)
        )
        result = await self._session.execute(stmt)
        return {change.undoes_id: change for change in result.scalars().all()}

    async def latest_for_each(
        self, target_type: str, target_ids: Collection[str]
    ) -> dict[str, Change]:
        """the newest change of each target, in one query."""
        if not target_ids:
            return {}
        newest = (
            select(
                Change.id,
                func.row_number()
                .over(
                    partition_by=Change.target_id,
                    order_by=(Change.created_at.desc(), Change.id.desc()),
                )
                .label("rank"),
            )
            .where(
                Change.tenant_id == self._tenant_id,
                Change.target_type == target_type,
                Change.target_id.in_(target_ids),
            )
            .subquery()
        )
        stmt = (
            select(Change)
            .join(newest, Change.id == newest.c.id)
            .where(newest.c.rank == 1)
        )
        result = await self._session.execute(stmt)
        return {change.target_id: change for change in result.scalars().all()}
