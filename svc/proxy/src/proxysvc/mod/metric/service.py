from __future__ import annotations

import re

from sqlalchemy.exc import IntegrityError

from qbrixcore.engine import EngineError
from qbrixcore.engine import ScoreRange
from qbrixcore.engine import check_metric
from qbrixstore.postgres.session import get_session

from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import MetricInvalidError
from proxysvc.core.error import MetricNameTakenError
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.metric.repository import MetricRepository
from proxysvc.mod.metric.serialize import metric_to_dict

DEFAULT_WINDOW_SECONDS = 24 * 60 * 60
NAME_MAX_LENGTH = 64

_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")


def _taken(name: str) -> MetricNameTakenError:
    return MetricNameTakenError(f"a metric named {name!r} already exists")


class MetricService:
    """the metrics a workspace's loops improve.

    a metric is created at version 1.0; its type and range never change.
    """

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
    ) -> dict:
        if len(name) > NAME_MAX_LENGTH or not _NAME.fullmatch(name):
            raise MetricInvalidError(
                f"a metric name is what code sends: lowercase letters, digits, "
                f"'_', '-' and '.', starting with a letter or digit, at most "
                f"{NAME_MAX_LENGTH} characters, got {name!r}"
            )
        try:
            declared = ScoreRange(*score_range) if score_range is not None else None
            checked_type = check_metric(metric_type, declared)
        except EngineError as e:
            raise MetricInvalidError(str(e)) from e
        if window_seconds <= 0:
            raise MetricInvalidError(
                f"a window is a positive number of seconds, got {window_seconds}"
            )
        if not semantic.strip():
            raise MetricInvalidError("a metric needs a semantic: what it stands for")

        async with get_session() as session:
            repo = MetricRepository(session, tenant_id)
            if await repo.get_by_name(name) is not None:
                raise _taken(name)
            try:
                metric = await repo.create(
                    name,
                    checked_type,
                    declared,
                    semantic.strip(),
                    window_seconds,
                    actor.user_id,
                )
            except IntegrityError as e:
                raise _taken(name) from e
            metric_dict = metric_to_dict(metric)
            await ChangeRepository(session, tenant_id).record(
                "metric.create", "metric", metric.id, actor, after=metric_dict
            )
        return metric_dict

    @staticmethod
    async def get_metric(tenant_id: str, ref: str) -> dict | None:
        async with get_session() as session:
            metric = await MetricRepository(session, tenant_id).resolve(ref)
            return metric_to_dict(metric) if metric else None

    @staticmethod
    async def list_metrics(tenant_id: str) -> list[dict]:
        async with get_session() as session:
            metrics = await MetricRepository(session, tenant_id).list()
            return [metric_to_dict(metric) for metric in metrics]

    @staticmethod
    async def delete_metric(
        tenant_id: str,
        metric_id: str,
        *,
        actor: Actor,
        undoing: Undoing | None = None,
    ) -> bool:
        async with get_session() as session:
            repo = MetricRepository(session, tenant_id)
            metric = await repo.get(metric_id)
            if metric is None:
                return False
            loop = await LoopRepository(session, tenant_id).first_using_metric(
                metric_id
            )
            if loop is not None:
                raise ChangeConflictError(
                    f"the loop {loop.key!r} uses the metric {metric.name!r}, "
                    f"so it cannot be deleted"
                )
            before = metric_to_dict(metric)
            await repo.delete(metric)
            await ChangeRepository(session, tenant_id).record(
                "metric.delete",
                "metric",
                metric_id,
                actor,
                before=before,
                undoing=undoing,
            )
        return True
