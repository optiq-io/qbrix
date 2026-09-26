from __future__ import annotations

import asyncio
from concurrent import futures
from typing import Sequence

import grpc
from grpc_health.v1 import health as grpc_health
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from qbrixlog import get_logger

from qbrixruntime.config import GrpcSettings
from qbrixruntime.task import drain

logger = get_logger(__name__)

HEALTH_SERVICE_NAME = health_pb2.DESCRIPTOR.services_by_name["Health"].full_name


def build_server(
    settings: GrpcSettings,
    *,
    interceptors: Sequence[grpc.aio.ServerInterceptor] | None = None,
) -> grpc.aio.Server:
    return grpc.aio.server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc_server_thread_pool_size),
        interceptors=interceptors,
        options=[
            (
                "grpc.http2.min_recv_ping_interval_without_data_ms",
                settings.grpc_server_min_recv_ping_interval_ms,
            ),
            (
                "grpc.keepalive_permit_without_calls",
                int(settings.grpc_server_keepalive_permit_without_calls),
            ),
            # disable GOAWAY ENHANCE_YOUR_CALM on too-frequent client pings (trusted internal traffic)
            ("grpc.http2.max_ping_strikes", 0),
        ],
    )


async def add_health(
    server: grpc.aio.Server, service_name: str
) -> grpc_health.aio.HealthServicer:
    servicer = grpc_health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(servicer, server)
    await servicer.set(service_name, health_pb2.HealthCheckResponse.SERVING)
    return servicer


def enable_reflection(server: grpc.aio.Server, *service_names: str) -> None:
    reflection.enable_server_reflection(
        (*service_names, reflection.SERVICE_NAME), server
    )


def bind(server: grpc.aio.Server, settings: GrpcSettings) -> str:
    listen_addr = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)
    return listen_addr


async def serve_until_shutdown(
    server: grpc.aio.Server,
    shutdown: asyncio.Event,
    *,
    grace: float,
    health: grpc_health.aio.HealthServicer | None = None,
) -> None:
    """serve until the process is asked to terminate, then drain within ``grace``.

    the health servicer, when given, is moved to NOT_SERVING before the drain
    begins. kubernetes grpc probes check the overall ("") entry, which the
    servicer sets to SERVING at construction and nothing else ever changes, so
    without this a pod keeps reporting ready for its whole termination window.
    """
    terminated = asyncio.ensure_future(server.wait_for_termination())
    stopping = asyncio.ensure_future(shutdown.wait())
    try:
        await asyncio.wait({terminated, stopping}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if health is not None:
            try:
                await health.enter_graceful_shutdown()
            except Exception as e:  # noqa
                # advisory only; it must not be able to hold up the drain.
                logger.error("failed to report NOT_SERVING: %s", e)
        # stop before cancelling the waiter: cancelling grpc's
        # wait_for_termination() while the server is still running propagates
        # the cancellation into this task and kills teardown.
        await server.stop(grace=grace)
        await drain(terminated, stopping)
