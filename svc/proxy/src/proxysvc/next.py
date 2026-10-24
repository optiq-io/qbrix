from __future__ import annotations

import grpc
from fastapi import FastAPI

from qbrixlog import get_logger

from proxysvc.config import ProxySettings

logger = get_logger(__name__)


def next_routes(app: FastAPI, settings: ProxySettings) -> None:
    if not settings.next_enabled:
        return
    from proxysvc.transport.http.router.loop import router as loop_router
    from proxysvc.transport.http.router.metric import router as metric_router

    app.include_router(metric_router, prefix="/api/v1")
    app.include_router(loop_router, prefix="/api/v1")
    logger.info("next routes registered")


def next_servicers(server: grpc.aio.Server, settings: ProxySettings) -> tuple[str, ...]:
    """register the next grpc services and return their names for reflection."""
    if not settings.next_enabled:
        return ()
    logger.info("next grpc services registered")
    return ()
