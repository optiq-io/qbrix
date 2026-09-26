from __future__ import annotations

import logging
from fastapi import APIRouter
from fastapi import status
from fastapi import Depends
from fastapi import Query
from pydantic import BaseModel

from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
from proxysvc.transport.http.auth.dependencies import get_current_user_id
from proxysvc.transport.http.auth.dependencies import require_feature
from proxysvc.transport.http.auth.dependencies import require_scopes
from proxysvc.transport.http.exception import InternalServerException
from proxysvc.transport.http.router.analytics import get_clickhouse_client
from proxysvc.mod.experiment.repository import ExperimentRepository
from qbrixstore.postgres.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/insight/experiment",
    tags=["insight"],
    dependencies=[Depends(require_feature("insights"))],
)


async def _resolve_experiment_ids(
    tenant_id: str, experiment_id: str
) -> str | list[str]:
    """resolve experiment ids for insight queries.

    for meta-bandit experiments, returns learner experiment ids so insights
    aggregate actual arm-level data. for normal experiments, returns
    the experiment_id as-is.
    """
    async with get_session() as session:
        repo = ExperimentRepository(session, tenant_id)
        experiment = await repo.get(experiment_id)
        if (
            experiment is not None
            and experiment.policy == "MetaBanditPolicy"
            and experiment.meta_experiment_id is None
        ):
            learners = experiment.policy_params.get("learners", [])
            if learners:
                return learners
    return experiment_id


class ExperimentStatsResponse(BaseModel):
    experiment_id: str
    total_selections: int
    default_selections: int
    unique_contexts: int
    first_selection_ms: int | None
    last_selection_ms: int | None
    total_feedback: int
    avg_reward: float | None
    min_reward: float | None
    max_reward: float | None


class TimeseriesPointResponse(BaseModel):
    timestamp_ms: int
    selections: int
    default_selections: int


class TimeseriesResponse(BaseModel):
    experiment_id: str
    interval_ms: int
    data: list[TimeseriesPointResponse]


class ArmStatsResponse(BaseModel):
    arm_index: int
    arm_name: str
    selections: int
    feedback_count: int
    avg_reward: float | None


class ArmAnalyticsResponse(BaseModel):
    experiment_id: str
    arms: list[ArmStatsResponse]


class RewardTimeseriesPoint(BaseModel):
    timestamp_ms: int
    avg_reward: float
    feedback_count: int


class RewardTimeseriesResponse(BaseModel):
    data: list[RewardTimeseriesPoint]


class ArmTimeseriesArm(BaseModel):
    arm_index: int
    arm_name: str
    selections: int


class ArmTimeseriesPoint(BaseModel):
    timestamp_ms: int
    arms: list[ArmTimeseriesArm]


class ArmTimeseriesResponse(BaseModel):
    data: list[ArmTimeseriesPoint]


class FeedbackFunnelResponse(BaseModel):
    total_selections: int
    total_feedback: int
    feedback_rate: float


class CumulativeRewardPoint(BaseModel):
    timestamp_ms: int
    cumulative_reward: float
    cumulative_count: int


class CumulativeRewardResponse(BaseModel):
    data: list[CumulativeRewardPoint]


@router.get(
    "/{experiment_id}",
    status_code=status.HTTP_200_OK,
    response_model=ExperimentStatsResponse,
)
async def get_experiment_stats(
    experiment_id: str,
    start_ms: int | None = Query(None, description="start timestamp in ms"),
    end_ms: int | None = Query(None, description="end timestamp in ms"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["insight:read"])),
):
    """get aggregated stats for an experiment."""
    try:
        query_ids = await _resolve_experiment_ids(tenant_id, experiment_id)
        client = get_clickhouse_client()
        stats = client.get_experiment_stats(
            tenant_id=tenant_id,
            experiment_id=query_ids,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        return ExperimentStatsResponse(
            experiment_id=experiment_id,
            total_selections=stats["total_selections"],
            default_selections=stats["default_selections"],
            unique_contexts=stats["unique_contexts"],
            first_selection_ms=stats["first_selection_ms"],
            last_selection_ms=stats["last_selection_ms"],
            total_feedback=stats["total_feedback"],
            avg_reward=stats["avg_reward"],
            min_reward=stats["min_reward"],
            max_reward=stats["max_reward"],
        )
    except Exception as e:
        logger.error(f"failed to get experiment stats: {e}")
        raise InternalServerException("failed to get experiment stats")


@router.get(
    "/{experiment_id}/timeseries",
    status_code=status.HTTP_200_OK,
    response_model=TimeseriesResponse,
)
async def get_experiment_timeseries(
    experiment_id: str,
    interval_ms: int = Query(
        3600000, description="bucket interval in ms (default 1 hour)"
    ),
    start_ms: int | None = Query(None, description="start timestamp in ms"),
    end_ms: int | None = Query(None, description="end timestamp in ms"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["insight:read"])),
):
    """get time series data for an experiment."""
    try:
        query_ids = await _resolve_experiment_ids(tenant_id, experiment_id)
        client = get_clickhouse_client()
        data = client.get_experiment_timeseries(
            tenant_id=tenant_id,
            experiment_id=query_ids,
            interval_ms=interval_ms,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        return TimeseriesResponse(
            experiment_id=experiment_id,
            interval_ms=interval_ms,
            data=[
                TimeseriesPointResponse(
                    timestamp_ms=point["timestamp_ms"],
                    selections=point["selections"],
                    default_selections=point["default_selections"],
                )
                for point in data
            ],
        )
    except Exception as e:
        logger.error(f"failed to get experiment timeseries: {e}")
        raise InternalServerException("failed to get experiment timeseries")


@router.get(
    "/{experiment_id}/arms",
    status_code=status.HTTP_200_OK,
    response_model=ArmAnalyticsResponse,
)
async def get_arm_analytics(
    experiment_id: str,
    start_ms: int | None = Query(None, description="start timestamp in ms"),
    end_ms: int | None = Query(None, description="end timestamp in ms"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["insight:read"])),
):
    """get per-arm statistics for an experiment."""
    try:
        query_ids = await _resolve_experiment_ids(tenant_id, experiment_id)
        client = get_clickhouse_client()
        arms = client.get_arm_stats(
            tenant_id=tenant_id,
            experiment_id=query_ids,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        return ArmAnalyticsResponse(
            experiment_id=experiment_id,
            arms=[
                ArmStatsResponse(
                    arm_index=arm["arm_index"],
                    arm_name=arm["arm_name"],
                    selections=arm["selections"],
                    feedback_count=arm["feedback_count"],
                    avg_reward=arm["avg_reward"],
                )
                for arm in arms
            ],
        )
    except Exception as e:
        logger.error(f"failed to get arm analytics: {e}")
        raise InternalServerException("failed to get arm analytics")


@router.get(
    "/{experiment_id}/timeseries/rewards",
    status_code=status.HTTP_200_OK,
    response_model=RewardTimeseriesResponse,
)
async def get_reward_timeseries(
    experiment_id: str,
    interval_ms: int = Query(..., description="bucket interval in ms"),
    start_ms: int | None = Query(None, description="start timestamp in ms"),
    end_ms: int | None = Query(None, description="end timestamp in ms"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["insight:read"])),
):
    """get bucketed avg reward timeseries for an experiment."""
    try:
        query_ids = await _resolve_experiment_ids(tenant_id, experiment_id)
        client = get_clickhouse_client()
        data = client.get_reward_timeseries(
            tenant_id=tenant_id,
            experiment_id=query_ids,
            interval_ms=interval_ms,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        return RewardTimeseriesResponse(
            data=[
                RewardTimeseriesPoint(
                    timestamp_ms=point["timestamp_ms"],
                    avg_reward=point["avg_reward"],
                    feedback_count=point["feedback_count"],
                )
                for point in data
            ]
        )
    except Exception as e:
        logger.error(f"failed to get reward timeseries: {e}")
        raise InternalServerException("failed to get reward timeseries")


@router.get(
    "/{experiment_id}/timeseries/arms",
    status_code=status.HTTP_200_OK,
    response_model=ArmTimeseriesResponse,
)
async def get_arm_timeseries(
    experiment_id: str,
    interval_ms: int = Query(..., description="bucket interval in ms"),
    start_ms: int | None = Query(None, description="start timestamp in ms"),
    end_ms: int | None = Query(None, description="end timestamp in ms"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["insight:read"])),
):
    """get per-arm selections timeseries for an experiment."""
    try:
        query_ids = await _resolve_experiment_ids(tenant_id, experiment_id)
        client = get_clickhouse_client()
        data = client.get_arm_timeseries(
            tenant_id=tenant_id,
            experiment_id=query_ids,
            interval_ms=interval_ms,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        return ArmTimeseriesResponse(
            data=[
                ArmTimeseriesPoint(
                    timestamp_ms=point["timestamp_ms"],
                    arms=[
                        ArmTimeseriesArm(
                            arm_index=arm["arm_index"],
                            arm_name=arm["arm_name"],
                            selections=arm["selections"],
                        )
                        for arm in point["arms"]
                    ],
                )
                for point in data
            ]
        )
    except Exception as e:
        logger.error(f"failed to get arm timeseries: {e}")
        raise InternalServerException("failed to get arm timeseries")


@router.get(
    "/{experiment_id}/funnel",
    status_code=status.HTTP_200_OK,
    response_model=FeedbackFunnelResponse,
)
async def get_feedback_funnel(
    experiment_id: str,
    start_ms: int | None = Query(None, description="start timestamp in ms"),
    end_ms: int | None = Query(None, description="end timestamp in ms"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["insight:read"])),
):
    """get selection vs feedback funnel metrics for an experiment."""
    try:
        query_ids = await _resolve_experiment_ids(tenant_id, experiment_id)
        client = get_clickhouse_client()
        funnel = client.get_feedback_funnel(
            tenant_id=tenant_id,
            experiment_id=query_ids,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        return FeedbackFunnelResponse(
            total_selections=funnel["total_selections"],
            total_feedback=funnel["total_feedback"],
            feedback_rate=funnel["feedback_rate"],
        )
    except Exception as e:
        logger.error(f"failed to get feedback funnel: {e}")
        raise InternalServerException("failed to get feedback funnel")


@router.get(
    "/{experiment_id}/cumulative",
    status_code=status.HTTP_200_OK,
    response_model=CumulativeRewardResponse,
)
async def get_cumulative_reward(
    experiment_id: str,
    interval_ms: int = Query(..., description="bucket interval in ms"),
    start_ms: int | None = Query(None, description="start timestamp in ms"),
    end_ms: int | None = Query(None, description="end timestamp in ms"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["insight:read"])),
):
    """get cumulative reward over time for an experiment."""
    try:
        query_ids = await _resolve_experiment_ids(tenant_id, experiment_id)
        client = get_clickhouse_client()
        data = client.get_cumulative_reward(
            tenant_id=tenant_id,
            experiment_id=query_ids,
            interval_ms=interval_ms,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        return CumulativeRewardResponse(
            data=[
                CumulativeRewardPoint(
                    timestamp_ms=point["timestamp_ms"],
                    cumulative_reward=point["cumulative_reward"],
                    cumulative_count=point["cumulative_count"],
                )
                for point in data
            ]
        )
    except Exception as e:
        logger.error(f"failed to get cumulative reward: {e}")
        raise InternalServerException("failed to get cumulative reward")
