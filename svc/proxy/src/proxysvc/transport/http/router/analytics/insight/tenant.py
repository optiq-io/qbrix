from __future__ import annotations

import logging
from fastapi import APIRouter
from fastapi import status
from fastapi import Depends
from fastapi import Query
from pydantic import BaseModel

from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import require_feature
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import InternalServerException
from proxysvc.transport.http.router.analytics import get_clickhouse_client
from proxysvc.mod.experiment.repository import ExperimentRepository
from qbrixstore.postgres.session import get_session

logger = logging.getLogger(__name__)

# deliberately a sibling of the `/experiment` router rather than a route on it:
# that router owns `/{experiment_id}`, which would match `workspace` first and
# turn every call here into a lookup for an experiment named "workspace".
router = APIRouter(
    prefix="/insight/workspace",
    tags=["insight"],
    dependencies=[Depends(require_feature("insights"))],
)

# the same ceiling the console's list calls use. a workspace past this has a
# table that paginates anyway, and the batch stops being one frame's worth.
MAX_EXPERIMENTS = 200


class ArmStatsResponse(BaseModel):
    arm_index: int
    arm_name: str
    selections: int
    feedback_count: int
    avg_reward: float | None


class ExperimentArmStatsResponse(BaseModel):
    experiment_id: str
    arms: list[ArmStatsResponse]


class WorkspaceArmStatsResponse(BaseModel):
    experiments: list[ExperimentArmStatsResponse]


async def _query_plan(tenant_id: str) -> tuple[list[str], dict[str, str]]:
    """the ids to query, and how each folds back to an experiment the user sees.

    meta-bandit learners carry the events but are not listed anywhere in the
    console, so they are queried under their own ids and then attributed to the
    parent — the same fold `_resolve_experiment_ids` does one experiment at a
    time on the per-experiment routes.
    """
    async with get_session() as session:
        repo = ExperimentRepository(session, tenant_id)
        experiments = await repo.list(limit=MAX_EXPERIMENTS)

        query_ids: list[str] = []
        fold: dict[str, str] = {}
        for exp in experiments:
            query_ids.append(exp.id)
            fold[exp.id] = exp.id
            if exp.policy != "MetaBanditPolicy":
                continue
            for learner_id in exp.policy_params.get("learners", []):
                query_ids.append(learner_id)
                fold[learner_id] = exp.id

    return query_ids, fold


@router.get(
    "/arms",
    status_code=status.HTTP_200_OK,
    response_model=WorkspaceArmStatsResponse,
)
async def get_workspace_arm_stats(
    start_ms: int | None = Query(None, description="start timestamp in ms"),
    end_ms: int | None = Query(None, description="end timestamp in ms"),
    tenant_id: str = Depends(get_current_tenant_id),
    _user=Depends(require_scopes(["insight:read"])),
):
    """per-arm statistics for every experiment in the workspace, in one call.

    the console's home table draws a row per experiment out of exactly this,
    and before this endpoint it asked for each one separately — 2N requests
    that could not even start until the experiment list had come back.
    """
    try:
        query_ids, fold = await _query_plan(tenant_id)
        if not query_ids:
            return WorkspaceArmStatsResponse(experiments=[])

        client = get_clickhouse_client()
        raw = client.get_arm_stats_batch(
            tenant_id=tenant_id,
            experiment_ids=query_ids,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        # (experiment, arm_index) -> accumulator. a fold target collects the
        # arms of every learner underneath it, so an index shared by two
        # learners becomes one arm carrying both their totals.
        merged: dict[tuple[str, int], dict] = {}
        for queried_id, arms in raw.items():
            target = fold.get(queried_id)
            if target is None:
                continue
            for arm in arms:
                key = (target, arm["arm_index"])
                acc = merged.setdefault(
                    key,
                    {
                        "arm_index": arm["arm_index"],
                        "arm_name": arm["arm_name"],
                        "name_weight": -1,
                        "selections": 0,
                        "feedback_count": 0,
                        "reward_sum": 0.0,
                    },
                )
                acc["selections"] += arm["selections"]
                acc["feedback_count"] += arm["feedback_count"]
                acc["reward_sum"] += arm["reward_sum"]
                # learners of one meta-bandit share a pool, so this only ever
                # arbitrates a disagreement that should not exist — take the
                # name the most traffic was actually served under.
                if arm["selections"] > acc["name_weight"]:
                    acc["name_weight"] = arm["selections"]
                    acc["arm_name"] = arm["arm_name"]

        by_experiment: dict[str, list[ArmStatsResponse]] = {}
        for (experiment_id, _), arm in sorted(merged.items()):
            by_experiment.setdefault(experiment_id, []).append(
                ArmStatsResponse(
                    arm_index=arm["arm_index"],
                    arm_name=arm["arm_name"],
                    selections=arm["selections"],
                    feedback_count=arm["feedback_count"],
                    avg_reward=(
                        arm["reward_sum"] / arm["feedback_count"]
                        if arm["feedback_count"]
                        else None
                    ),
                )
            )

        return WorkspaceArmStatsResponse(
            experiments=[
                ExperimentArmStatsResponse(experiment_id=experiment_id, arms=arms)
                for experiment_id, arms in by_experiment.items()
            ]
        )
    except Exception as e:
        logger.error(f"failed to get workspace arm stats: {e}")
        raise InternalServerException("failed to get workspace arm stats")
