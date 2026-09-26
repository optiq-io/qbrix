from __future__ import annotations

import logging
from typing import Optional

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

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/event",
    tags=["event"],
    dependencies=[Depends(require_feature("event_log"))],
)


# --- unified event log ---


class EventResponse(BaseModel):
    name: str
    tenant_id: str
    resource_id: str
    timestamp_ms: int
    category: str
    data: dict


class EventListResponse(BaseModel):
    events: list[EventResponse]
    limit: int
    offset: int


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=EventListResponse,
)
async def list_events(
    category: Optional[str] = Query(
        None, description="filter by category: selection, feedback, audit"
    ),
    resource_id: Optional[str] = Query(None, description="filter by resource id"),
    start_ms: Optional[int] = Query(None, description="start timestamp in ms"),
    end_ms: Optional[int] = Query(None, description="end timestamp in ms"),
    limit: int = Query(100, le=500, description="max results to return"),
    offset: int = Query(0, ge=0, description="offset for pagination"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["trace:read"])),
):
    """list events from the unified event log."""
    try:
        client = get_clickhouse_client()
        results = client.query_events(
            tenant_id=tenant_id,
            event_category=category,
            resource_id=resource_id,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
            offset=offset,
        )

        events = [
            EventResponse(
                name=r["name"],
                tenant_id=r["tenant_id"],
                resource_id=r["resource_id"],
                timestamp_ms=r["timestamp_ms"],
                category=r["category"],
                data=r["data"] if isinstance(r["data"], dict) else {},
            )
            for r in results
        ]

        return EventListResponse(events=events, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"failed to list events: {e}")
        raise InternalServerException("failed to list events")


@router.get(
    "/experiment/{experiment_id}/activity",
    status_code=status.HTTP_200_OK,
    response_model=EventListResponse,
)
async def get_experiment_activity(
    experiment_id: str,
    category: Optional[str] = Query(
        None, description="filter by category: selection, feedback, audit"
    ),
    since_ms: Optional[int] = Query(
        None, description="only events at or after this timestamp in ms"
    ),
    until_ms: Optional[int] = Query(
        None, description="only events strictly before this timestamp in ms"
    ),
    limit: int = Query(100, le=500, description="max results to return"),
    offset: int = Query(0, ge=0, description="offset for pagination"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["trace:read"])),
):
    """unified per-experiment activity feed across selection, feedback, and audit.

    offset paging is only stable under an upper bound: the feed grows at the head,
    so without until_ms every new event shifts the window and pages back repeat
    rows already shown.
    """
    try:
        client = get_clickhouse_client()
        results = client.query_events(
            tenant_id=tenant_id,
            event_category=category,
            resource_id=experiment_id,
            start_ms=since_ms,
            end_ms=until_ms,
            limit=limit,
            offset=offset,
        )

        events = [
            EventResponse(
                name=r["name"],
                tenant_id=r["tenant_id"],
                resource_id=r["resource_id"],
                timestamp_ms=r["timestamp_ms"],
                category=r["category"],
                data=r["data"] if isinstance(r["data"], dict) else {},
            )
            for r in results
        ]

        return EventListResponse(events=events, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"failed to get experiment activity: {e}")
        raise InternalServerException("failed to get experiment activity")


# --- selection events ---


class SelectionEventResponse(BaseModel):
    tenant_id: str
    experiment_id: str
    request_id: str
    arm_id: str
    arm_name: str
    arm_index: int
    is_default: bool
    context_id: str
    timestamp_ms: int
    policy: str


class SelectionEventListResponse(BaseModel):
    events: list[SelectionEventResponse]
    limit: int
    offset: int


class FeedbackEventResponse(BaseModel):
    tenant_id: str
    experiment_id: str
    request_id: str
    arm_index: int
    reward: float
    context_id: str
    timestamp_ms: int


class SelectionDetailResponse(BaseModel):
    selection: SelectionEventResponse | None
    feedback: FeedbackEventResponse | None


@router.get(
    "/selection",
    status_code=status.HTTP_200_OK,
    response_model=SelectionEventListResponse,
)
async def list_selection_events(
    experiment_id: Optional[str] = Query(None, description="filter by experiment id"),
    limit: int = Query(100, le=500, description="max results to return"),
    offset: int = Query(0, ge=0, description="offset for pagination"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["trace:read"])),
):
    """list selection events."""
    try:
        client = get_clickhouse_client()
        results = client.query_selection_events(
            tenant_id=tenant_id,
            experiment_id=experiment_id,
            limit=limit,
            offset=offset,
        )

        events = [
            SelectionEventResponse(
                tenant_id=r["tenant_id"],
                experiment_id=r["experiment_id"],
                request_id=r["request_id"],
                arm_id=r["arm_id"],
                arm_name=r["arm_name"],
                arm_index=r["arm_index"],
                is_default=r["is_default"],
                context_id=r["context_id"],
                timestamp_ms=r["timestamp_ms"],
                policy=r["policy"],
            )
            for r in results
        ]

        return SelectionEventListResponse(events=events, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"failed to list selection events: {e}")
        raise InternalServerException("failed to list selection events")


@router.get(
    "/selection/{request_id}",
    status_code=status.HTTP_200_OK,
    response_model=SelectionDetailResponse,
)
async def get_selection_detail(
    request_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["trace:read"])),
):
    """get full detail for a selection request (selection + matched feedback)."""
    try:
        client = get_clickhouse_client()

        selection_results = client.query_selection_events(
            tenant_id=tenant_id,
            request_id=request_id,
            limit=1,
        )

        feedback_results = client.query_feedback_events(
            tenant_id=tenant_id,
            request_id=request_id,
            limit=1,
        )

        selection = None
        if selection_results:
            r = selection_results[0]
            selection = SelectionEventResponse(
                tenant_id=r["tenant_id"],
                experiment_id=r["experiment_id"],
                request_id=r["request_id"],
                arm_id=r["arm_id"],
                arm_name=r["arm_name"],
                arm_index=r["arm_index"],
                is_default=r["is_default"],
                context_id=r["context_id"],
                timestamp_ms=r["timestamp_ms"],
                policy=r["policy"],
            )

        feedback = None
        if feedback_results:
            r = feedback_results[0]
            feedback = FeedbackEventResponse(
                tenant_id=r["tenant_id"],
                experiment_id=r["experiment_id"],
                request_id=r["request_id"],
                arm_index=r["arm_index"],
                reward=r["reward"],
                context_id=r["context_id"],
                timestamp_ms=r["timestamp_ms"],
            )

        return SelectionDetailResponse(selection=selection, feedback=feedback)
    except Exception as e:
        logger.error(f"failed to get selection detail: {e}")
        raise InternalServerException("failed to get selection detail")


# --- feedback events ---


class FeedbackEventListResponse(BaseModel):
    events: list[FeedbackEventResponse]
    limit: int
    offset: int


@router.get(
    "/feedback",
    status_code=status.HTTP_200_OK,
    response_model=FeedbackEventListResponse,
)
async def list_feedback_events(
    experiment_id: Optional[str] = Query(None, description="filter by experiment id"),
    limit: int = Query(100, le=500, description="max results to return"),
    offset: int = Query(0, ge=0, description="offset for pagination"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["trace:read"])),
):
    """list feedback events."""
    try:
        client = get_clickhouse_client()
        results = client.query_feedback_events(
            tenant_id=tenant_id,
            experiment_id=experiment_id,
            limit=limit,
            offset=offset,
        )

        events = [
            FeedbackEventResponse(
                tenant_id=r["tenant_id"],
                experiment_id=r["experiment_id"],
                request_id=r["request_id"],
                arm_index=r["arm_index"],
                reward=r["reward"],
                context_id=r["context_id"],
                timestamp_ms=r["timestamp_ms"],
            )
            for r in results
        ]

        return FeedbackEventListResponse(events=events, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"failed to list feedback events: {e}")
        raise InternalServerException("failed to list feedback events")


# --- audit events ---


class AuditEventResponse(BaseModel):
    name: str
    tenant_id: str
    actor_id: str
    resource_type: str
    resource_id: str
    payload: str
    timestamp_ms: int


class AuditEventListResponse(BaseModel):
    events: list[AuditEventResponse]
    limit: int
    offset: int


@router.get(
    "/audit",
    status_code=status.HTTP_200_OK,
    response_model=AuditEventListResponse,
)
async def list_audit_events(
    name: Optional[str] = Query(None, description="filter by event name"),
    resource_type: Optional[str] = Query(None, description="filter by resource type"),
    resource_id: Optional[str] = Query(None, description="filter by resource id"),
    limit: int = Query(100, le=500, description="max results to return"),
    offset: int = Query(0, ge=0, description="offset for pagination"),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
    _user=Depends(require_scopes(["trace:read"])),
):
    """list audit events."""
    try:
        client = get_clickhouse_client()
        results = client.query_audit_events(
            tenant_id=tenant_id,
            name=name,
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
            offset=offset,
        )

        events = [
            AuditEventResponse(
                name=r["name"],
                tenant_id=r["tenant_id"],
                actor_id=r["actor_id"],
                resource_type=r["resource_type"],
                resource_id=r["resource_id"],
                payload=r["payload"],
                timestamp_ms=r["timestamp_ms"],
            )
            for r in results
        ]

        return AuditEventListResponse(events=events, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"failed to list audit events: {e}")
        raise InternalServerException("failed to list audit events")
