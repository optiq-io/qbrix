from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from datetime import datetime
from datetime import timezone
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Change
from qbrixstore.postgres.session import get_session
from qbrixstore.redis import Learning

from proxysvc.core import cursor as pages
from proxysvc.core.actor import Actor
from proxysvc.core.actor import Approval
from proxysvc.core.error import ChangeAnsweredError
from proxysvc.core.error import ChangeAnswerForbiddenError
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeMovedError
from proxysvc.core.error import ChangeNoLongerAppliesError
from proxysvc.core.error import ChangeNotUndoableError
from proxysvc.core.error import LoopInvalidError
from proxysvc.core.error import LoopKeyTakenError
from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import LoopStateError
from proxysvc.core.error import MetricInvalidError
from proxysvc.core.error import MetricNameTakenError
from proxysvc.core.error import MetricNotFoundError
from proxysvc.mod.change.entry import COUNTS_WITHIN
from proxysvc.mod.change.entry import TargetName
from proxysvc.mod.change.entry import counts
from proxysvc.mod.change.entry import fold as fold_bursts
from proxysvc.mod.change.entry import workspace_entry
from proxysvc.mod.change.applied import Applied
from proxysvc.mod.change.proposal import DECLINED
from proxysvc.mod.change.proposal import HAPPENED
from proxysvc.mod.change.proposal import WAITING
from proxysvc.mod.change.proposal import Draft
from proxysvc.mod.change.proposal import Proposed
from proxysvc.mod.change.proposal import Waiting
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.repository import moved_since
from proxysvc.mod.change.serialize import change_to_dict
from proxysvc.mod.change.serialize import snapshot
from proxysvc.mod.change.undo import NOT_UNDOABLE
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.change.undo import is_undoable
from proxysvc.mod.connection.repository import ConnectionRepository
from proxysvc.mod.connection.serialize import levels_snapshot
from proxysvc.mod.connection.serialize import overrides_of
from proxysvc.mod.experiment.repository import ExperimentRepository
from proxysvc.mod.experiment.serialize import experiment_to_dict
from proxysvc.mod.gate.repository import FeatureGateRepository
from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.serialize import loop_to_dict
from proxysvc.mod.people import People
from proxysvc.mod.metric.repository import MetricRepository
from proxysvc.mod.metric.serialize import metric_to_dict
from proxysvc.mod.pool.repository import PoolRepository
from proxysvc.mod.pool.serialize import pool_to_dict
from proxysvc.util import _parse_datetime

if TYPE_CHECKING:
    from proxysvc.mod.connection.service import ConnectionService
    from proxysvc.mod.experiment.service import ExperimentService
    from proxysvc.mod.gate import GateService
    from proxysvc.mod.loop.service import LoopService
    from proxysvc.mod.metric.service import MetricService
    from proxysvc.mod.pool.service import PoolService

_RESTORABLE_EXPERIMENT_FIELDS = ("name", "enabled", "policy_params")
_LEARNING_KINDS = ("experiment.reset", "experiment.restore")
_UNVERSIONED = ("version", "updated_at")
_RESTORABLE_LOOP_FIELDS = ("name", "key", "state", "committed")
_REFUSED_NOW = (
    ChangeConflictError,
    ChangeNotUndoableError,
    LoopInvalidError,
    LoopKeyTakenError,
    LoopStateError,
    MetricInvalidError,
    MetricNameTakenError,
)


def _changed_fields(change: Change) -> list[str]:
    return [
        name
        for name in _RESTORABLE_EXPERIMENT_FIELDS
        if change.before[name] != change.after[name]
    ]


def _restored_loop_fields(change: Change) -> tuple[str, ...]:
    """what an undo of this change writes back: only the fields it moved, so an
    unrelated later change doesn't refuse it. undoing a create removes the loop,
    so anything changed since refuses it. a key locks at launch, so undoing a
    key's change also needs the loop still in that state."""
    if change.before is None:
        return _RESTORABLE_LOOP_FIELDS
    moved = {
        name
        for name in _RESTORABLE_LOOP_FIELDS
        if change.before.get(name) != change.after.get(name)
    }
    if "key" in moved:
        moved.add("state")
    return tuple(moved)


def _unversioned_gate(config: dict | None) -> dict | None:
    """a gate as an undo compares it. a period keeps the offset it was written
    with but reads back in utc, so it compares as an instant."""
    if config is None:
        return None
    stripped = {k: v for k, v in config.items() if k not in _UNVERSIONED}
    experiment = {
        k: v for k, v in config["experiment"].items() if k not in _UNVERSIONED
    }
    period = experiment["schedule"]["period"]
    experiment["schedule"] = {
        **experiment["schedule"],
        "period": {
            **period,
            "start": _parse_datetime(period["start"]),
            "end": _parse_datetime(period["end"]),
        },
    }
    stripped["experiment"] = experiment
    return stripped


def _restored_part(change: Change, state: dict | None) -> dict | None:
    """the part of a target's state an undo of this change writes back."""
    if change.target_type == "gate":
        return _unversioned_gate(state)
    if state is None:
        return None
    if change.target_type == "connection":
        return state["levels"]
    if change.kind == "experiment.update":
        return {name: state[name] for name in _changed_fields(change)}
    if change.target_type == "loop":
        return {name: state.get(name) for name in _restored_loop_fields(change)}
    return {"name": state["name"]}


def _check_answerable(change: Change, actor: Actor) -> None:
    """a waiting change is answered by the person its connection acts for,
    themselves: not another member, not an admin, not a key or a connection."""
    person = actor.kind == "member" and not actor.api_key_id
    if not person or actor.user_id != change.actor_user_id:
        raise ChangeAnswerForbiddenError(
            "only the person a connection acts for answers its changes"
        )
    if change.status != WAITING:
        raise ChangeAnsweredError(
            f"change {change.id} is {change.status}, not waiting for an answer"
        )


def _ref(change: Change) -> dict:
    return {
        "id": change.id,
        "kind": change.kind,
        "undoable": is_undoable(change.kind),
    }


async def _targets(
    session: AsyncSession, tenant_id: str, loop: str | None, metric: str | None
) -> list[tuple[str, str]]:
    """the targets a loop or metric filter names, which must exist."""
    targets = []
    if loop is not None:
        found = await LoopRepository(session, tenant_id).resolve(loop)
        if found is None:
            raise LoopNotFoundError(loop)
        targets.append(("loop", found.id))
    if metric is not None:
        named = await MetricRepository(session, tenant_id).resolve(metric)
        if named is None:
            raise MetricNotFoundError(metric)
        targets.append(("metric", named.id))
    return targets


async def workspace_rows(
    session: AsyncSession, tenant_id: str, groups: list[list[Change]]
) -> list[dict]:
    """the entries for these groups, every name they mention read in a fixed
    number of queries, however many the page holds. a target that is gone goes by
    its last name, from the snapshot of its latest change."""
    changes = [change for group in groups for change in group]
    repo = ChangeRepository(session, tenant_id)
    undoers = await repo.undone_by_each([change.id for change in changes])
    people = await People.load(
        session,
        tenant_id,
        [c.actor_user_id for c in changes]
        + [c.decided_by_user_id for c in changes if c.decided_by_user_id]
        + [u.actor_user_id for u in undoers.values()],
    )
    loops = await LoopRepository(session, tenant_id).names(
        {c.target_id for c in changes if c.target_type == "loop"}
    )
    metrics = await MetricRepository(session, tenant_id).names(
        {c.target_id for c in changes if c.target_type == "metric"}
    )
    targets = {
        **{
            ("loop", loop_id): TargetName(name=name, key=key)
            for loop_id, (key, name) in loops.items()
        },
        **{
            ("metric", metric_id): TargetName(name=name)
            for metric_id, name in metrics.items()
        },
    }
    for target_type in ("loop", "metric"):
        gone = {
            c.target_id
            for c in changes
            if c.target_type == target_type
            and (target_type, c.target_id) not in targets
        }
        latest = await repo.latest_for_each(target_type, gone)
        for target_id, change in latest.items():
            last = change.before or change.after or {}
            targets[(target_type, target_id)] = TargetName(
                name=last.get("name"), key=last.get("key")
            )
    return [workspace_entry(group, people, targets, undoers) for group in groups]


async def _current_state(
    session: AsyncSession, tenant_id: str, change: Change
) -> dict | None:
    if change.target_type == "experiment":
        experiment = await ExperimentRepository(session, tenant_id).get(
            change.target_id
        )
        return snapshot(experiment_to_dict(experiment)) if experiment else None
    if change.target_type == "gate":
        repo = FeatureGateRepository(session, tenant_id)
        gate = await repo.get(change.target_id)
        return repo.to_config(gate).model_dump(mode="json") if gate else None
    if change.target_type == "metric":
        metric = await MetricRepository(session, tenant_id).get(change.target_id)
        return metric_to_dict(metric) if metric else None
    if change.target_type == "connection":
        connection = await ConnectionRepository(session).get(
            tenant_id, change.target_id
        )
        if connection is None:
            return None
        return levels_snapshot(connection, overrides_of(connection))
    if change.target_type == "loop":
        loop = await LoopRepository(session, tenant_id).get(change.target_id)
        if loop is None:
            return None
        people = await People.load(session, tenant_id, [loop.owner_user_id])
        return loop_to_dict(loop, people)
    pool = await PoolRepository(session, tenant_id).get(change.target_id)
    return pool_to_dict(pool) if pool else None


class ChangeService:
    """reads the change log, and undoes a change as a new one.

    writes record their own change, inside their own transaction, through
    ChangeRepository. an undo goes through the owning service's write path, so
    the redis sync and cache invalidation run as for any other write.
    """

    def __init__(
        self,
        *,
        experiments: ExperimentService,
        gates: GateService,
        pools: PoolService,
        metrics: MetricService,
        loops: LoopService,
        connections: ConnectionService,
    ):
        self._experiments = experiments
        self._gates = gates
        self._pools = pools
        self._metrics = metrics
        self._loops = loops
        self._connections = connections

    async def list_changes(
        self, tenant_id: str, target_type: str, target_id: str, limit: int = 50
    ) -> list[dict]:
        async with get_session() as session:
            repo = ChangeRepository(session, tenant_id)
            changes = await repo.list_for(target_type, target_id, limit=limit)
            return [change_to_dict(change) for change in changes]

    async def get_change(self, tenant_id: str, change_id: str) -> dict | None:
        async with get_session() as session:
            repo = ChangeRepository(session, tenant_id)
            change = await repo.get(change_id)
            return change_to_dict(change) if change else None

    async def list_workspace(
        self,
        tenant_id: str,
        *,
        who: Collection[str] = (),
        kinds: Collection[str] = (),
        except_kinds: Collection[str] = (),
        loop: str | None = None,
        metric: str | None = None,
        undoable: bool | None = None,
        statuses: Collection[str] = HAPPENED,
        fold: bool = True,
        cursor: str | None = None,
        limit: int,
    ) -> dict:
        """every change in the workspace, newest first. limit counts changes,
        not rows: a fold is computed on the page, so the cursor never moves with
        it, and one cut by the page's end goes on as its own row on the next."""
        before = pages.decode(cursor) if cursor else None
        async with get_session() as session:
            targets = await _targets(session, tenant_id, loop, metric)
            rows = await ChangeRepository(session, tenant_id).page_workspace(
                before,
                limit + 1,
                actor_kinds=who,
                kinds=kinds,
                except_kinds=except_kinds,
                targets=targets,
                undoable=undoable,
                statuses=statuses,
            )
            changes, next_cursor = pages.page(rows, limit)
            groups = fold_bursts(changes) if fold else [[c] for c in changes]
            return {
                "changes": await workspace_rows(session, tenant_id, groups),
                "next_cursor": next_cursor,
            }

    async def count_workspace(
        self,
        tenant_id: str,
        *,
        who: Collection[str] = (),
        kinds: Collection[str] = (),
        loop: str | None = None,
        metric: str | None = None,
        undoable: bool | None = None,
    ) -> dict:
        """how many changes the workspace made this week."""
        since = datetime.now(timezone.utc) - COUNTS_WITHIN
        async with get_session() as session:
            targets = await _targets(session, tenant_id, loop, metric)
            rows = await ChangeRepository(session, tenant_id).count_workspace(
                since, kinds=kinds, targets=targets, undoable=undoable
            )
        return {"since": since.isoformat(), **counts(rows, who)}

    async def get_entry(self, tenant_id: str, change_id: str) -> dict | None:
        async with get_session() as session:
            change = await ChangeRepository(session, tenant_id).get(change_id)
            if change is None:
                return None
            entries = await workspace_rows(session, tenant_id, [[change]])
            return entries[0]

    async def undo(
        self,
        tenant_id: str,
        change_id: str,
        *,
        actor: Actor,
        reason: str | None = None,
        plan_tier: str = "free",
    ) -> dict | None:
        """undo a change by writing its inverse, and return the new change.

        refused when the kind cannot be undone, when it was already undone, or
        when a later change moved what the undo would restore: undo never
        merges.
        """
        async with get_session() as session:
            repo = ChangeRepository(session, tenant_id)
            change = await repo.get(change_id)
            if change is None:
                return None
            await self._check_undoable(repo, change)
            later = await repo.list_after(change)
            await self._check_unchanged_since(session, tenant_id, change, later)
            baseline_applied = await self._baseline_applied(repo, change)

        undoing = Undoing(
            change_id=change.id,
            latest_id=later[0].id if later else change.id,
            reason=reason,
        )
        try:
            applied = await self._apply_inverse(
                tenant_id,
                change,
                actor=actor,
                undoing=undoing,
                plan_tier=plan_tier,
                baseline_applied=baseline_applied,
            )
        except Proposed as proposed:
            waiting = await self._wait(tenant_id, proposed.draft, actor, None)
            return change_to_dict(waiting)
        if not applied:
            raise ChangeConflictError(
                f"the {change.target_type} {change.target_id} no longer exists"
            )

        async with get_session() as session:
            undo = await ChangeRepository(session, tenant_id).undone_by(change.id)
            return change_to_dict(undo)

    @staticmethod
    async def _check_undoable(repo: ChangeRepository, change: Change) -> None:
        if change.status not in HAPPENED:
            raise ChangeNotUndoableError(
                f"change {change.id} is {change.status}: it never applied, so "
                f"there is nothing to undo"
            )
        if not is_undoable(change.kind):
            raise ChangeNotUndoableError(
                NOT_UNDOABLE.get(change.kind, f"{change.kind} cannot be undone")
            )
        if change.status == "undone":
            undo = await repo.undone_by(change.id)
            raise ChangeConflictError(
                f"change {change.id} was already undone by {undo.id if undo else 'another change'}"
            )

    async def act(
        self,
        tenant_id: str,
        kind: str,
        ref: str | None,
        args: dict,
        *,
        actor: Actor,
        reason: str | None = None,
        evidence: dict | None = None,
    ) -> Applied | Waiting | None:
        """a connection's change at its level for the kind: applied at once,
        or, when it must ask first, stored waiting for its person with args as
        the proposal its approval re-runs. None when the target isn't found."""
        try:
            return await self._make(
                tenant_id,
                kind,
                ref,
                args,
                actor=actor,
                reason=reason,
                evidence=evidence,
            )
        except Proposed as proposed:
            waiting = await self._wait(tenant_id, proposed.draft, actor, args)
            return Waiting(value=proposed.draft.before, change=_ref(waiting))

    async def approve(
        self,
        tenant_id: str,
        change_id: str,
        *,
        actor: Actor,
        role: str,
        where: str,
        raise_level: bool = False,
    ) -> dict | None:
        """apply a waiting change as its connection, with its person's yes.

        the write runs against the target as it is now, and the change that
        waited becomes the applied one. when the target no longer takes it,
        nothing applies and the change keeps waiting. raise_level then sets
        the connection to act and notify for that kind, as a change of its own.
        """
        async with get_session() as session:
            repo = ChangeRepository(session, tenant_id)
            change = await repo.get(change_id)
            if change is None:
                return None
            _check_answerable(change, actor)
            undone = await repo.get(change.undoes_id) if change.undoes_id else None
        if raise_level:
            await self._connections.levels(
                tenant_id, change.connection_id, user_id=actor.user_id, role=role
            )

        connection = replace(
            Actor.connection(
                change.actor_user_id,
                connection_id=change.connection_id,
                client_name=change.client_name or "",
                request_id=actor.request_id,
            ),
            level=change.level,
            approval=Approval(change_id=change.id, user_id=actor.user_id, where=where),
        )
        try:
            if undone is not None:
                made = await self.undo(
                    tenant_id, undone.id, actor=connection, reason=change.reason
                )
            else:
                made = await self._make(
                    tenant_id,
                    change.kind,
                    change.target_id,
                    change.proposal or {},
                    actor=connection,
                    reason=change.reason,
                    evidence=change.evidence,
                )
        except ChangeAnsweredError:
            raise
        except ChangeMovedError as e:
            raise ChangeNoLongerAppliesError(
                f"{e}. nothing was applied; the change still waits",
                e.later_change_id,
            ) from e
        except _REFUSED_NOW as e:
            raise await self._no_longer_applies(tenant_id, change, str(e)) from e
        if made is None:
            raise await self._no_longer_applies(
                tenant_id, change, f"the {change.target_type} is gone"
            )

        if raise_level:
            await self._connections.set_levels(
                tenant_id,
                change.connection_id,
                {undone.kind if undone else change.kind: "notify"},
                actor=actor,
                role=role,
                reason=f"raised when approving change {change.id}",
            )
        return await self.get_entry(tenant_id, change.id)

    async def decline(
        self,
        tenant_id: str,
        change_id: str,
        *,
        actor: Actor,
        where: str,
        reason: str | None = None,
    ) -> dict | None:
        """turn a waiting change down. it stays in history with the reason,
        which agents read before proposing it again."""
        async with get_session() as session:
            repo = ChangeRepository(session, tenant_id)
            change = await repo.get(change_id)
            if change is None:
                return None
            _check_answerable(change, actor)
            await repo.decide(
                change.id,
                status=DECLINED,
                user_id=actor.user_id,
                where=where,
                reason=reason,
            )
        return await self.get_entry(tenant_id, change_id)

    async def _wait(
        self, tenant_id: str, draft: Draft, actor: Actor, proposal: dict | None
    ) -> Change:
        async with get_session() as session:
            return await ChangeRepository(session, tenant_id).propose(
                draft, actor, proposal
            )

    async def _no_longer_applies(
        self, tenant_id: str, change: Change, refused: str
    ) -> ChangeNoLongerAppliesError:
        """the refusal, with the newest change since it was asked: what moved
        the target, when one did."""
        async with get_session() as session:
            later = await ChangeRepository(session, tenant_id).newest_since(
                change.target_type, change.target_id, change.asked_at
            )
        if later is None:
            return ChangeNoLongerAppliesError(
                f"{refused}. nothing was applied; the change still waits", None
            )
        return ChangeNoLongerAppliesError(
            f"{refused}: {later.kind} ({later.id}) changed the {change.target_type} "
            f"since this was asked. nothing was applied; the change still waits",
            later.id,
        )

    async def _make(
        self,
        tenant_id: str,
        kind: str,
        ref: str | None,
        args: dict,
        *,
        actor: Actor,
        reason: str | None,
        evidence: dict | None,
    ) -> Applied | None:
        """the write a kind of change makes, from its args. a waiting change
        stores args as its proposal, so asking and approving run the same."""
        loops = self._loops
        if kind == "loop.create":
            return await loops.create_loop(
                tenant_id, **args, actor=actor, reason=reason
            )
        if kind == "metric.create":
            score_range = args.get("score_range")
            return await self._metrics.create_metric(
                tenant_id,
                name=args["name"],
                semantic=args["semantic"],
                metric_type=args["metric_type"],
                score_range=tuple(score_range) if score_range else None,
                window_seconds=args["window_seconds"],
                actor=actor,
                reason=reason,
            )
        if kind == "note.add":
            return await loops.add_note(tenant_id, ref, text=args["text"], actor=actor)
        if kind == "loop.launch":
            return await loops.launch_loop(tenant_id, ref, actor=actor, reason=reason)
        if kind == "loop.rename":
            return await loops.rename_loop(
                tenant_id,
                ref,
                name=args.get("name"),
                key=args.get("key"),
                actor=actor,
                reason=reason,
            )
        if kind == "loop.commit":
            return await loops.commit_loop(
                tenant_id, ref, option=args["option"], actor=actor, reason=reason
            )
        if kind == "loop.reopen":
            return await loops.reopen_loop(tenant_id, ref, actor=actor, reason=reason)
        if kind == "loop.retire":
            return await loops.retire_loop(tenant_id, ref, actor=actor, reason=reason)
        if kind == "loop.pause":
            return await loops.pause_loop(
                tenant_id, ref, actor=actor, reason=reason, evidence=evidence
            )
        if kind == "loop.resume":
            return await loops.resume_loop(tenant_id, ref, actor=actor, reason=reason)
        if kind == "cycle.start":
            return await loops.start_cycle(
                tenant_id,
                ref,
                options=args.get("options"),
                engine=args.get("engine"),
                fallback=args.get("fallback"),
                actor=actor,
                reason=reason,
            )
        if kind == "cycle.reset":
            return await loops.reset_cycle(tenant_id, ref, actor=actor, reason=reason)
        raise ValueError(f"a connection doesn't make {kind} changes directly")

    @staticmethod
    async def _check_unchanged_since(
        session: AsyncSession, tenant_id: str, change: Change, later: list[Change]
    ) -> None:
        """refuse when what the undo restores no longer equals what the change
        left: a learning restore after a later reset or restore, otherwise
        the restored fields as they are now against the change's after."""
        if not later:
            return
        if change.kind in _LEARNING_KINDS:
            for newer in later:
                if newer.kind in _LEARNING_KINDS:
                    raise moved_since(newer)
            return
        current = await _current_state(session, tenant_id, change)
        if _restored_part(change, current) != _restored_part(change, change.after):
            raise moved_since(later[0])

    @staticmethod
    async def _baseline_applied(repo: ChangeRepository, change: Change) -> int:
        """the applied count the change left behind: none after a reset, the
        restored count after a restore."""
        if change.kind != "experiment.restore":
            return 0
        undone = await repo.get(change.undoes_id)
        return undone.learning[change.target_id]["applied"]

    async def _apply_inverse(
        self,
        tenant_id: str,
        change: Change,
        *,
        actor: Actor,
        undoing: Undoing,
        plan_tier: str,
        baseline_applied: int,
    ) -> bool:
        target_id = change.target_id
        before = change.before

        if change.kind == "experiment.update":
            restored = await self._experiments.restore_experiment(
                tenant_id,
                target_id,
                {name: before[name] for name in _changed_fields(change)},
                actor=actor,
                undoing=undoing,
                plan_tier=plan_tier,
            )
            return restored is not None

        if change.kind in _LEARNING_KINDS:
            entry = change.learning[target_id]
            restored = await self._experiments.restore_learning(
                tenant_id,
                target_id,
                Learning(
                    params=entry["params"],
                    applied=entry["applied"],
                    last_id=entry["last_id"],
                ),
                baseline_applied=baseline_applied,
                actor=actor,
                undoing=undoing,
            )
            return restored is not None

        if change.kind == "gate.create":
            return await self._gates.delete_gate_config(
                tenant_id, target_id, actor=actor, undoing=undoing
            )

        if change.kind == "gate.delete":
            restored = await self._gates.create_gate_config(
                tenant_id,
                target_id,
                GateConfigRequest.from_snapshot(before),
                actor=actor,
                undoing=undoing,
            )
            return restored is not None

        if change.kind in ("gate.replace", "gate.patch"):
            restored = await self._gates.update_gate_config(
                tenant_id,
                target_id,
                GateConfigRequest.from_snapshot(before),
                actor=actor,
                undoing=undoing,
            )
            return restored is not None

        if change.kind == "pool.update":
            restored = await self._pools.update_pool(
                tenant_id, target_id, actor=actor, undoing=undoing, name=before["name"]
            )
            return restored is not None

        if change.kind == "metric.create":
            return await self._metrics.delete_metric(
                tenant_id, target_id, actor=actor, undoing=undoing
            )

        if change.kind == "connection.levels":
            return await self._connections.restore_levels(
                tenant_id,
                target_id,
                before["levels"],
                actor=actor,
                undoing=undoing,
            )

        if change.kind == "loop.create":
            return await self._loops.delete_loop(
                tenant_id, target_id, actor=actor, undoing=undoing
            )

        if change.kind == "loop.rename":
            restored = await self._loops.rename_loop(
                tenant_id,
                target_id,
                name=before["name"],
                key=before["key"],
                actor=actor,
                undoing=undoing,
            )
            return restored is not None

        if change.kind == "loop.commit":
            reopened = await self._loops.reopen_loop(
                tenant_id, target_id, actor=actor, undoing=undoing
            )
            return reopened is not None

        if change.kind == "loop.reopen":
            committed = await self._loops.commit_loop(
                tenant_id,
                target_id,
                option=before["committed"],
                actor=actor,
                undoing=undoing,
            )
            return committed is not None

        if change.kind == "loop.pause":
            resumed = await self._loops.resume_loop(
                tenant_id, target_id, actor=actor, undoing=undoing
            )
            return resumed is not None

        if change.kind == "loop.resume":
            paused = await self._loops.pause_loop(
                tenant_id, target_id, actor=actor, undoing=undoing
            )
            return paused is not None

        raise ChangeNotUndoableError(f"{change.kind} cannot be undone")
