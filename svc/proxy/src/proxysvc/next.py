from __future__ import annotations

import grpc
from fastapi import FastAPI

from qbrixlog import get_logger

from proxysvc.config import ProxySettings

logger = get_logger(__name__)


def next_routes(app: FastAPI, settings: ProxySettings) -> None:
    if not settings.next_enabled:
        return
    logger.info("next routes registered")


def next_servicers(server: grpc.aio.Server, settings: ProxySettings) -> tuple[str, ...]:
    """register the next grpc services and return their names for reflection."""
    if not settings.next_enabled:
        return ()
    logger.info("next grpc services registered")
    return ()
