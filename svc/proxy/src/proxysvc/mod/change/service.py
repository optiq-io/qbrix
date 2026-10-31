from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from qbrixstore.postgres.models import Change
from qbrixstore.postgres.session import get_session
from qbrixstore.redis import Learning

from proxysvc.core import cursor as pages
from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeNotUndoableError
from proxysvc.core.error import LoopNotFoundError
from proxysvc.core.error import MetricNotFoundError
from proxysvc.mod.change.entry import TargetName
from proxysvc.mod.change.entry import fold as fold_bursts
from proxysvc.mod.change.entry import workspace_entry
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.repository import moved_since
from proxysvc.mod.change.serialize import change_to_dict
from proxysvc.mod.change.serialize import snapshot
from proxysvc.mod.change.undo import NOT_UNDOABLE
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.change.undo import is_undoable
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
    from proxysvc.mod.experiment.service import ExperimentService
    from proxysvc.mod.gate import GateService
    from proxysvc.mod.loop.service import LoopService
    from proxysvc.mod.metric.service import MetricService
    from proxysvc.mod.pool.service import PoolService

_RESTORABLE_EXPERIMENT_FIELDS = ("name", "enabled", "policy_params")
_LEARNING_KINDS = ("experiment.reset", "experiment.restore")
_UNVERSIONED = ("version", "updated_at")
_RESTORABLE_LOOP_FIELDS = ("name", "key", "state")


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
        if change.before[name] != change.after[name]
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
    if change.kind == "experiment.update":
        return {name: state[name] for name in _changed_fields(change)}
    if change.target_type == "loop":
        return {name: state[name] for name in _restored_loop_fields(change)}
    return {"name": state["name"]}


async def _rows(
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
    ):
        self._experiments = experiments
        self._gates = gates
        self._pools = pools
        self._metrics = metrics
        self._loops = loops

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
        loop: str | None = None,
        metric: str | None = None,
        undoable: bool | None = None,
        fold: bool = True,
        cursor: str | None = None,
        limit: int,
    ) -> dict:
        """every change in the workspace, newest first. limit counts changes,
        not rows: a fold is computed on the page, so the cursor never moves with
        it, and one cut by the page's end goes on as its own row on the next."""
        before = pages.decode(cursor) if cursor else None
        async with get_session() as session:
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
            rows = await ChangeRepository(session, tenant_id).page_workspace(
                before,
                limit + 1,
                actor_kinds=who,
                kinds=kinds,
                targets=targets,
                undoable=undoable,
            )
            changes, next_cursor = pages.page(rows, limit)
            groups = fold_bursts(changes) if fold else [[c] for c in changes]
            return {
                "changes": await _rows(session, tenant_id, groups),
                "next_cursor": next_cursor,
            }

    async def get_entry(self, tenant_id: str, change_id: str) -> dict | None:
        async with get_session() as session:
            change = await ChangeRepository(session, tenant_id).get(change_id)
            if change is None:
                return None
            entries = await _rows(session, tenant_id, [[change]])
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
        applied = await self._apply_inverse(
            tenant_id,
            change,
            actor=actor,
            undoing=undoing,
            plan_tier=plan_tier,
            baseline_applied=baseline_applied,
        )
        if not applied:
            raise ChangeConflictError(
                f"the {change.target_type} {change.target_id} no longer exists"
            )

        async with get_session() as session:
            undo = await ChangeRepository(session, tenant_id).undone_by(change.id)
            return change_to_dict(undo)

    @staticmethod
    async def _check_undoable(repo: ChangeRepository, change: Change) -> None:
        if not is_undoable(change.kind):
            raise ChangeNotUndoableError(
                NOT_UNDOABLE.get(change.kind, f"{change.kind} cannot be undone")
            )
        if change.status == "undone":
            undo = await repo.undone_by(change.id)
            raise ChangeConflictError(
                f"change {change.id} was already undone by {undo.id if undo else 'another change'}"
            )

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
