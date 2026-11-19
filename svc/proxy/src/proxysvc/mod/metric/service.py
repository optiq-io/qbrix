from __future__ import annotations

import re
from typing import TYPE_CHECKING
from typing import Literal
from typing import get_args

from sqlalchemy.exc import IntegrityError

from qbrixcore.engine import EngineError
from qbrixcore.engine import ScoreRange
from qbrixcore.engine import check_metric
from qbrixstore.postgres.session import get_session

from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import MetricInUseError
from proxysvc.core.error import MetricInvalidError
from proxysvc.core.error import MetricNameTakenError
from proxysvc.mod.change.applied import Applied
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.metric.repository import MetricRepository
from proxysvc.mod.metric.route import MetricRouteCache
from proxysvc.mod.metric.serialize import metric_detail
from proxysvc.mod.metric.serialize import metric_to_dict
from proxysvc.mod.people import People

if TYPE_CHECKING:
    from proxysvc.mod.loop.service import LoopService

DEFAULT_WINDOW_SECONDS = 24 * 60 * 60
NAME_MAX_LENGTH = 64

_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")

SemanticChange = Literal["reword", "same", "new"]
SEMANTIC_CHANGES: tuple[str, ...] = get_args(SemanticChange)


def _taken(name: str) -> MetricNameTakenError:
    return MetricNameTakenError(f"a metric named {name!r} already exists")


def _check_name(name: str) -> None:
    if len(name) > NAME_MAX_LENGTH or not _NAME.fullmatch(name):
        raise MetricInvalidError(
            f"a metric name is what code sends: lowercase letters, digits, "
            f"'_', '-' and '.', starting with a letter or digit, at most "
            f"{NAME_MAX_LENGTH} characters, got {name!r}"
        )


def _check_window(window_seconds: int) -> None:
    if window_seconds <= 0:
        raise MetricInvalidError(
            f"a window is a positive number of seconds, got {window_seconds}"
        )


def _checked_semantic(semantic: str) -> str:
    if not semantic.strip():
        raise MetricInvalidError("a metric needs a semantic: what it stands for")
    return semantic.strip()


class MetricService:
    """the metrics a workspace's loops improve.

    a metric is created at version 1.0; its type and range never change. a
    new window, or the same semantic said anew, is a minor version; a new
    semantic is a major one, which every loop still deciding takes with a new
    cycle. a reworded semantic is no version: the current one's text changes.
    """

    def __init__(self, routes: MetricRouteCache, loops: LoopService):
        self._routes = routes
        self._loops = loops

    @staticmethod
    async def create_metric(
        tenant_id: str,
        *,
        name: str,
        semantic: str,
        metric_type: str,
        score_range: tuple[float, float] | None = None,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        actor: Actor,
        reason: str | None = None,
    ) -> Applied:
        _check_name(name)
        try:
            declared = ScoreRange(*score_range) if score_range is not None else None
            checked_type = check_metric(metric_type, declared)
        except EngineError as e:
            raise MetricInvalidError(str(e)) from e
        _check_window(window_seconds)
        semantic = _checked_semantic(semantic)

        async with get_session() as session:
            repo = MetricRepository(session, tenant_id)
            if await repo.get_by_name(name) is not None:
                raise _taken(name)
            try:
                metric = await repo.create(
                    name,
                    checked_type,
                    declared,
                    semantic,
                    window_seconds,
                    actor.user_id,
                )
            except IntegrityError as e:
                raise _taken(name) from e
            metric_dict = metric_to_dict(metric)
            change = await ChangeRepository(session, tenant_id).record(
                "metric.create",
                "metric",
                metric.id,
                actor,
                after=metric_dict,
                reason=reason,
            )
        return Applied.of(metric_dict, change)

    @staticmethod
    async def get_metric(tenant_id: str, ref: str) -> dict | None:
        async with get_session() as session:
            metric = await MetricRepository(session, tenant_id).resolve(ref)
            return metric_to_dict(metric) if metric else None

    @staticmethod
    async def metric_detail(tenant_id: str, ref: str) -> dict | None:
        """a metric with its versions, newest first: who made each, when, why
        and what it changed."""
        async with get_session() as session:
            metric = await MetricRepository(session, tenant_id).resolve(ref)
            if metric is None:
                return None
            changes = await ChangeRepository(session, tenant_id).list_for(
                "metric", metric.id, limit=None
            )
            people = await People.load(
                session, tenant_id, [v.created_by for v in metric.versions]
            )
            return metric_detail(metric, changes, people)

    @staticmethod
    async def list_metrics(tenant_id: str) -> list[dict]:
        async with get_session() as session:
            metrics = await MetricRepository(session, tenant_id).list()
            return [metric_to_dict(metric) for metric in metrics]

    @staticmethod
    async def metrics_in_use(tenant_id: str) -> list[dict]:
        """every metric, with the loops that use it."""
        async with get_session() as session:
            metrics = await MetricRepository(session, tenant_id).list()
            using = await LoopRepository(session, tenant_id).using_metrics(
                [metric.id for metric in metrics]
            )
            return [
                {
                    **metric_to_dict(metric),
                    "loops": [
                        {
                            "id": loop.id,
                            "key": loop.key,
                            "name": loop.name,
                            "state": loop.state,
                        }
                        for loop in using.get(metric.id, [])
                    ],
                }
                for metric in metrics
            ]

    async def update_metric(
        self,
        tenant_id: str,
        ref: str,
        *,
        name: str | None = None,
        window_seconds: int | None = None,
        semantic: str | None = None,
        semantic_change: SemanticChange | None = None,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """change a metric's name, window or semantic as one change, recorded
        on the metric and in the history of every loop using it.

        the name is what code sends, so it changes only while no decision has
        used it.
        """
        if (semantic is None) != (semantic_change is None):
            raise MetricInvalidError(
                "a new semantic says how its meaning changed: reword, same or new"
                if semantic_change is None
                else "say the new semantic along with how its meaning changed"
            )
        if semantic_change is not None and semantic_change not in SEMANTIC_CHANGES:
            raise MetricInvalidError(
                f"a semantic changes as {', '.join(SEMANTIC_CHANGES)}, "
                f"got {semantic_change!r}"
            )
        if name is not None:
            _check_name(name)
        if window_seconds is not None:
            _check_window(window_seconds)
        if semantic is not None:
            semantic = _checked_semantic(semantic)

        async with get_session() as session:
            repo = MetricRepository(session, tenant_id)
            metric = await repo.resolve(ref)
            if metric is None:
                return None
            current = metric.versions[-1]
            old_name = metric.name
            renamed = name is not None and name != old_name
            windowed = (
                window_seconds is not None and window_seconds != current.window_sec
            )
            if semantic is not None and semantic == current.semantic:
                raise MetricInvalidError(
                    f"the semantic of {old_name!r} already reads {semantic!r}"
                )
            if not (renamed or windowed or semantic is not None):
                raise MetricInvalidError(
                    f"nothing changes: {old_name!r} already has that name and window"
                )

            users = await self._loops.metric_users(session, tenant_id, metric.id)
            before = metric_to_dict(metric)
            if renamed:
                launched = await repo.first_launched(metric)
                if launched is not None:
                    raise MetricInUseError(
                        f"the loop {launched.key!r} has made decisions under "
                        f"{old_name!r}, and the name is what code sends, so it "
                        f"can't change; create a new metric instead"
                    )
                if await repo.get_by_name(name) is not None:
                    raise _taken(name)
                metric.name = name
                try:
                    await session.flush()
                except IntegrityError as e:
                    raise _taken(name) from e

            next_semantic = semantic if semantic is not None else current.semantic
            next_window = window_seconds if windowed else current.window_sec
            try:
                if semantic_change == "new":
                    await repo.add_version(
                        metric,
                        major=current.major + 1,
                        minor=0,
                        semantic=next_semantic,
                        window_sec=next_window,
                        created_by=actor.user_id,
                    )
                elif windowed or semantic_change == "same":
                    await repo.add_version(
                        metric,
                        major=current.major,
                        minor=current.minor + 1,
                        semantic=next_semantic,
                        window_sec=next_window,
                        created_by=actor.user_id,
                    )
                elif semantic_change == "reword":
                    current.semantic = next_semantic
                    await session.flush()
            except IntegrityError as e:
                raise ChangeConflictError(
                    f"{old_name!r} changed while this change was made; read it "
                    f"again and retry"
                ) from e

            after = metric_to_dict(metric)
            change = await ChangeRepository(session, tenant_id).record(
                "metric.update",
                "metric",
                metric.id,
                actor,
                before=before,
                after=after,
                reason=reason,
                undoing=undoing,
            )
            written = await self._loops.follow_metric(
                session,
                tenant_id,
                users,
                cycle=semantic_change == "new",
                actor=actor,
                reason=change.reason,
            )
        await self._loops.publish_all(tenant_id, written)
        await self._routes.drop(tenant_id, old_name)
        cycles = [
            {"loop": step.loop["key"], "cycle": step.loop["cycle"]["number"]}
            for step in written
            if step.started
        ]
        return Applied.of({"metric": after, "cycles": cycles}, change)

    async def delete_metric(
        self,
        tenant_id: str,
        ref: str,
        *,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """delete a metric no loop has used. once one has, it stays."""
        async with get_session() as session:
            repo = MetricRepository(session, tenant_id)
            metric = await repo.resolve(ref)
            if metric is None:
                return None
            used = await repo.first_user(metric)
            if used is not None:
                how = "uses" if used.metric_id == metric.id else "has used"
                raise MetricInUseError(
                    f"the loop {used.key!r} {how} the metric {metric.name!r}, "
                    f"so it can't be deleted"
                )
            before = metric_to_dict(metric)
            await repo.delete(metric)
            change = await ChangeRepository(session, tenant_id).record(
                "metric.delete",
                "metric",
                before["id"],
                actor,
                before=before,
                reason=reason,
                undoing=undoing,
            )
        await self._routes.drop(tenant_id, before["name"])
        return Applied.of(before, change)
