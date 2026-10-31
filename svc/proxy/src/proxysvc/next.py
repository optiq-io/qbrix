from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI

from qbrixlog import get_logger

from proxysvc.config import ProxySettings
from proxysvc.service import ProxyService

logger = get_logger(__name__)


def next_routes(app: FastAPI, settings: ProxySettings) -> None:
    if not settings.next_enabled:
        return
    from proxysvc.transport.http.router.connection import router as connection_router
    from proxysvc.transport.http.router.loop import router as loop_router
    from proxysvc.transport.http.router.metric import router as metric_router
    from proxysvc.transport.http.router.oauth import request_router
    from proxysvc.transport.http.router.oauth import router as oauth_router
    from proxysvc.transport.http.router.outcome import router as outcome_router
    from proxysvc.transport.http.router.pin import router as pin_router
    from proxysvc.transport.http.router.select import router as select_router

    app.include_router(metric_router, prefix="/api/v1")
    app.include_router(loop_router, prefix="/api/v1")
    app.include_router(select_router, prefix="/api/v1")
    app.include_router(outcome_router, prefix="/api/v1")
    app.include_router(connection_router, prefix="/api/v1")
    app.include_router(request_router, prefix="/api/v1")
    app.include_router(pin_router, prefix="/api/v1")
    app.include_router(oauth_router)

    from proxysvc.transport.mcp.server import mount

    mount(app, settings)
    logger.info("next routes registered")


@asynccontextmanager
async def next_lifespan(app: FastAPI, settings: ProxySettings) -> AsyncIterator[None]:
    """runs what the next routes need for as long as the app serves."""
    if not settings.next_enabled:
        yield
        return
    from proxysvc.transport.mcp.server import running

    async with running(app):
        yield


def next_servicers(
    server: grpc.aio.Server, settings: ProxySettings, service: ProxyService
) -> tuple[str, ...]:
    """register the next grpc services and return their names for reflection."""
    if not settings.next_enabled:
        return ()
    from qbrixproto import loop_pb2
    from qbrixproto import loop_pb2_grpc

    from proxysvc.transport.grpc.loop import LoopGRPCServicer

    loop_pb2_grpc.add_LoopServiceServicer_to_server(LoopGRPCServicer(service), server)
    logger.info("next grpc services registered")
    return (loop_pb2.DESCRIPTOR.services_by_name["LoopService"].full_name,)
