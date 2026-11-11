from __future__ import annotations

from collections.abc import Collection
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone

from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Change

from proxysvc.core.actor import Actor
from proxysvc.core.actor import Approval
from proxysvc.core.cursor import Position
from proxysvc.core.error import ChangeAnsweredError
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeMovedError
from proxysvc.core.error import ChangeWaitingError
from proxysvc.mod.change.note import NOTE_KINDS
from proxysvc.mod.change.proposal import HAPPENED
from proxysvc.mod.change.proposal import WAITING
from proxysvc.mod.change.proposal import Draft
from proxysvc.mod.change.proposal import Proposed
from proxysvc.mod.change.undo import UNDOABLE_KINDS
from proxysvc.mod.change.undo import Undoing


def moved_since(later: Change) -> ChangeMovedError:
    return ChangeMovedError(
        f"a later change exists on this {later.target_type}: {later.kind} "
        f"({later.id}). undo that one first",
        later_change_id=later.id,
    )


def _already_waiting(waiting: Change) -> ChangeWaitingError:
    return ChangeWaitingError(
        f"a {waiting.kind} change already waits on this {waiting.target_type} "
        f"({waiting.id}). its person answers it first",
        waiting_change_id=waiting.id,
    )


def _older_than(before: Position):
    created_at, change_id = before
    return or_(
        Change.created_at < created_at,
        and_(Change.created_at == created_at, Change.id < change_id),
    )


def _kind_filters(kinds: Collection[str], except_kinds: Collection[str]) -> list:
    filters = []
    if kinds:
        filters.append(Change.kind.in_(kinds))
    if except_kinds:
        filters.append(Change.kind.not_in(except_kinds))
    return filters


def _workspace_filters(
    *,
    kinds: Collection[str] = (),
    except_kinds: Collection[str] = (),
    targets: Collection[tuple[str, str]] = (),
    undoable: bool | None = None,
    statuses: Collection[str] = HAPPENED,
) -> list:
    """every filter given narrows the changes, targets included."""
    filters = _kind_filters(kinds, except_kinds)
    filters.append(Change.status.in_(statuses))
    for target_type, target_id in targets:
        filters.append(Change.target_type == target_type)
        filters.append(Change.target_id == target_id)
    if undoable is not None:
        can_undo = and_(Change.kind.in_(UNDOABLE_KINDS), Change.status == "applied")
        filters.append(can_undo if undoable else not_(can_undo))
    return filters


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

        a change whose actor must ask first is not recorded: Proposed unwinds
        the write instead. once approved, the same write turns the waiting
        change into this one.
        """
        if undoing is not None:
            await self._mark_undone(undoing, target_type, target_id)
            reason = undoing.reason
        if actor.level == "ask" and actor.approval is None:
            raise Proposed(
                Draft(
                    kind=kind,
                    target_type=target_type,
                    target_id=target_id,
                    before=before,
                    after=after,
                    learning=learning,
                    reason=reason,
                    evidence=evidence,
                    undoes_id=undoing.change_id if undoing else None,
                )
            )
        if actor.approval is not None:
            return await self._approve(
                actor,
                target_id=target_id,
                before=before,
                after=after,
                learning=learning,
            )
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
            level=actor.level or None,
        )
        self._session.add(change)
        await self._session.flush()
        return change

    async def propose(
        self, draft: Draft, actor: Actor, proposal: dict | None
    ) -> Change:
        """store a change that asks first, waiting, with what it would do."""
        waiting = await self.waiting_on(draft.target_type, draft.target_id, draft.kind)
        if waiting is not None:
            raise _already_waiting(waiting)
        now = datetime.now(timezone.utc)
        change = Change(
            tenant_id=self._tenant_id,
            kind=draft.kind,
            target_type=draft.target_type,
            target_id=draft.target_id,
            actor_kind=actor.kind,
            actor_user_id=actor.user_id,
            connection_id=actor.connection_id or None,
            client_name=actor.client_name or None,
            request_id=actor.request_id or None,
            reason=draft.reason,
            evidence=draft.evidence,
            before=draft.before,
            after=draft.after,
            learning=draft.learning,
            undoes_id=draft.undoes_id,
            status=WAITING,
            level=actor.level,
            proposal=proposal,
            asked_at=now,
            created_at=now,
        )
        self._session.add(change)
        try:
            await self._session.flush()
        except IntegrityError as e:
            await self._session.rollback()
            waiting = await self.waiting_on(
                draft.target_type, draft.target_id, draft.kind
            )
            if waiting is None:
                raise
            raise _already_waiting(waiting) from e
        return change

    async def waiting_on(
        self, target_type: str, target_id: str, kind: str
    ) -> Change | None:
        stmt = select(Change).where(
            Change.tenant_id == self._tenant_id,
            Change.target_type == target_type,
            Change.target_id == target_id,
            Change.kind == kind,
            Change.status == WAITING,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def decide(
        self,
        change_id: str,
        *,
        status: str,
        user_id: str,
        where: str,
        reason: str | None = None,
    ) -> None:
        """answer a waiting change, once: a concurrent answer is refused."""
        result = await self._session.execute(
            update(Change)
            .where(
                Change.id == change_id,
                Change.tenant_id == self._tenant_id,
                Change.status == WAITING,
            )
            .values(
                status=status,
                decided_by_user_id=user_id,
                decided_at=datetime.now(timezone.utc),
                decided_in=where,
                decision_reason=reason,
            )
        )
        if result.rowcount != 1:
            raise ChangeAnsweredError(f"change {change_id} was already answered")

    async def _approve(
        self,
        actor: Actor,
        *,
        target_id: str,
        before: dict | None,
        after: dict | None,
        learning: dict | None,
    ) -> Change:
        """the approved write, recorded on the change that waited for it: it
        happened now, so it moves to now; asked_at keeps when it was asked."""
        approval: Approval = actor.approval
        await self.decide(
            approval.change_id,
            status="applied",
            user_id=approval.user_id,
            where=approval.where,
        )
        await self._session.execute(
            update(Change)
            .where(Change.id == approval.change_id)
            .values(
                target_id=target_id,
                before=before,
                after=after,
                learning=learning,
                request_id=actor.request_id or None,
                created_at=datetime.now(timezone.utc),
            )
        )
        change = await self.get(approval.change_id)
        await self._session.refresh(change)
        return change

    async def _mark_undone(
        self, undoing: Undoing, target_type: str, target_id: str
    ) -> None:
        """inside the undo's transaction, so a change that lands after the
        undo was checked, or a concurrent undo, still refuses it."""
        latest = await self._latest_moving(target_type, target_id)
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

    async def _latest_moving(self, target_type: str, target_id: str) -> Change | None:
        stmt = (
            select(Change)
            .where(
                Change.tenant_id == self._tenant_id,
                Change.target_type == target_type,
                Change.target_id == target_id,
                Change.kind.not_in(NOTE_KINDS),
                Change.status.in_(HAPPENED),
            )
            .order_by(Change.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_after(self, change: Change) -> list[Change]:
        """later changes to the same target that moved it, newest first. a
        note moves nothing, so an undo looks past it."""
        stmt = (
            select(Change)
            .where(
                Change.tenant_id == self._tenant_id,
                Change.target_type == change.target_type,
                Change.target_id == change.target_id,
                Change.created_at > change.created_at,
                Change.kind.not_in(NOTE_KINDS),
                Change.status.in_(HAPPENED),
            )
            .order_by(Change.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def undone_by(self, change_id: str) -> Change | None:
        stmt = select(Change).where(
            Change.undoes_id == change_id,
            Change.tenant_id == self._tenant_id,
            Change.status.in_(HAPPENED),
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
        *,
        kinds: Collection[str] = (),
        except_kinds: Collection[str] = (),
        statuses: Collection[str] = HAPPENED,
    ) -> list[Change]:
        """an object's changes newest first, from just after before."""
        stmt = select(Change).where(
            Change.tenant_id == self._tenant_id,
            Change.target_type == target_type,
            Change.target_id == target_id,
            Change.status.in_(statuses),
            *_kind_filters(kinds, except_kinds),
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
        except_kinds: Collection[str] = (),
        targets: Collection[tuple[str, str]] = (),
        undoable: bool | None = None,
        statuses: Collection[str] = HAPPENED,
    ) -> list[Change]:
        """the workspace's changes newest first, from just after before."""
        stmt = select(Change).where(
            Change.tenant_id == self._tenant_id,
            *_workspace_filters(
                kinds=kinds,
                except_kinds=except_kinds,
                targets=targets,
                undoable=undoable,
                statuses=statuses,
            ),
        )
        if before is not None:
            stmt = stmt.where(_older_than(before))
        if actor_kinds:
            stmt = stmt.where(Change.actor_kind.in_(actor_kinds))
        stmt = stmt.order_by(Change.created_at.desc(), Change.id.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_workspace(
        self,
        since: datetime,
        *,
        kinds: Collection[str] = (),
        targets: Collection[tuple[str, str]] = (),
        undoable: bool | None = None,
    ) -> Sequence[tuple[str, str | None, str, int]]:
        """how many changes since then, per actor kind, client and status."""
        stmt = (
            select(Change.actor_kind, Change.client_name, Change.status, func.count())
            .where(
                Change.tenant_id == self._tenant_id,
                Change.created_at >= since,
                *_workspace_filters(kinds=kinds, targets=targets, undoable=undoable),
            )
            .group_by(Change.actor_kind, Change.client_name, Change.status)
        )
        result = await self._session.execute(stmt)
        return [tuple(row) for row in result.all()]

    async def newest_since(
        self, target_type: str, target_id: str, since: datetime
    ) -> Change | None:
        """the newest change that moved the target after a moment."""
        stmt = (
            select(Change)
            .where(
                Change.tenant_id == self._tenant_id,
                Change.target_type == target_type,
                Change.target_id == target_id,
                Change.created_at > since,
                Change.kind.not_in(NOTE_KINDS),
                Change.status.in_(HAPPENED),
            )
            .order_by(Change.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def undone_by_each(self, change_ids: Collection[str]) -> dict[str, Change]:
        """the change that undid each of these, in one query."""
        if not change_ids:
            return {}
        stmt = select(Change).where(
            Change.tenant_id == self._tenant_id,
            Change.undoes_id.in_(change_ids),
            Change.status.in_(HAPPENED),
        )
        result = await self._session.execute(stmt)
        return {change.undoes_id: change for change in result.scalars().all()}

    async def in_range(
        self, target_type: str, target_ids: Collection[str], since: datetime
    ) -> list[Change]:
        """every change that happened to these targets since then, oldest
        first, in one query."""
        if not target_ids:
            return []
        stmt = (
            select(Change)
            .where(
                Change.tenant_id == self._tenant_id,
                Change.target_type == target_type,
                Change.target_id.in_(target_ids),
                Change.created_at >= since,
                Change.status.in_(HAPPENED),
            )
            .order_by(Change.created_at, Change.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def _of_connections(self, user_id: str) -> tuple:
        """changes made through a person's connections, which only that
        person answers."""
        return (
            Change.tenant_id == self._tenant_id,
            Change.actor_user_id == user_id,
            Change.connection_id.is_not(None),
        )

    async def waiting_for(self, user_id: str) -> list[Change]:
        """what waits on a person's answer, oldest asked first."""
        stmt = (
            select(Change)
            .where(*self._of_connections(user_id), Change.status == WAITING)
            .order_by(Change.asked_at, Change.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_waiting_for(self, user_id: str) -> int:
        stmt = select(func.count()).where(
            *self._of_connections(user_id), Change.status == WAITING
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def notified_for(
        self, user_id: str, since: datetime, limit: int
    ) -> list[Change]:
        """what a person's connections did at act and notify since then,
        newest first."""
        stmt = (
            select(Change)
            .where(
                *self._of_connections(user_id),
                Change.level == "notify",
                Change.status.in_(HAPPENED),
                Change.created_at >= since,
            )
            .order_by(Change.created_at.desc(), Change.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def asked_by(
        self, user_id: str, connection_ids: Collection[str], since: datetime
    ) -> dict[tuple[str, str], tuple[int, int]]:
        """per connection and the kind whose level an approval would raise, how
        many changes it asked for since then and how many were approved. an
        undo asks at the level of the kind it undoes."""
        if not connection_ids:
            return {}
        undone = aliased(Change)
        kind = func.coalesce(undone.kind, Change.kind)
        approved = func.count().filter(Change.status.in_(HAPPENED))
        stmt = (
            select(Change.connection_id, kind, func.count(), approved)
            .outerjoin(undone, undone.id == Change.undoes_id)
            .where(
                Change.tenant_id == self._tenant_id,
                Change.actor_user_id == user_id,
                Change.connection_id.in_(connection_ids),
                Change.asked_at >= since,
            )
            .group_by(Change.connection_id, kind)
        )
        result = await self._session.execute(stmt)
        return {
            (connection_id, kind): (asked, approved)
            for connection_id, kind, asked, approved in result.all()
        }

    async def kinds_of(self, change_ids: Collection[str]) -> dict[str, str]:
        """each change's kind, in one query."""
        if not change_ids:
            return {}
        stmt = select(Change.id, Change.kind).where(
            Change.tenant_id == self._tenant_id, Change.id.in_(change_ids)
        )
        return {row.id: row.kind for row in (await self._session.execute(stmt)).all()}

    async def latest_for_each(
        self,
        target_type: str,
        target_ids: Collection[str],
        *,
        kinds: Collection[str] = (),
        before: datetime | None = None,
    ) -> dict[str, Change]:
        """the newest change of each target, of these kinds and from before
        then when given, in one query."""
        if not target_ids:
            return {}
        filters = _kind_filters(kinds, ())
        if before is not None:
            filters.append(Change.created_at < before)
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
                Change.status.in_(HAPPENED),
                *filters,
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
