import asyncio

import click
import grpc
import uvicorn

from qbrixlog import configure_logging
from qbrixlog import get_logger
from qbrixproto import proxy_pb2, proxy_pb2_grpc, auth_pb2_grpc
from qbrixproto import auth_pb2
from qbrixruntime.grpc import bind
from qbrixruntime.grpc import build_server
from qbrixruntime.grpc import enable_reflection
from qbrixruntime.grpc import serve_until_shutdown
from qbrixruntime.shutdown import shutdown_signal
from qbrixruntime.task import drain

from proxysvc.config import ProxySettings
from proxysvc.runtime import ProxyRuntime
from proxysvc.server import ProxyGRPCServicer
from proxysvc.transport.grpc.auth.server import AuthGRPCServicer
from proxysvc.transport.grpc.auth.interceptor import AuthInterceptor
from proxysvc.transport.grpc.exception.interceptor import ExceptionInterceptor

logger = get_logger(__name__)


def build_grpc_server(
    settings: ProxySettings, runtime: ProxyRuntime
) -> grpc.aio.Server:
    """assemble the grpc server and bind its listen address."""
    server = build_server(
        settings, interceptors=[ExceptionInterceptor(), AuthInterceptor(settings)]
    )

    proxy_pb2_grpc.add_ProxyServiceServicer_to_server(
        ProxyGRPCServicer(runtime.proxy_service), server
    )
    auth_pb2_grpc.add_AuthServiceServicer_to_server(
        AuthGRPCServicer(runtime.auth_service), server
    )

    enable_reflection(
        server,
        proxy_pb2.DESCRIPTOR.services_by_name["ProxyService"].full_name,
        auth_pb2.DESCRIPTOR.services_by_name["AuthService"].full_name,
    )

    bind(server, settings)
    return server


def build_http_server(settings: ProxySettings, runtime: ProxyRuntime) -> uvicorn.Server:
    """point the http routers at the runtime's services and build the server.

    the app is imported here rather than at module scope because importing it
    registers routers off the global settings, which the grpc-only path has no
    reason to pay for.
    """
    from proxysvc.transport.http.app import app
    from proxysvc.transport.http.router.agent import set_proxy_service as set_agent
    from proxysvc.transport.http.router.experiment import (
        set_proxy_service as set_experiment,
    )
    from proxysvc.transport.http.router.gate import set_proxy_service as set_gate
    from proxysvc.transport.http.router.pool import set_proxy_service as set_pool
    from proxysvc.transport.http.router.runtime import set_proxy_service as set_runtime

    for wire in (set_pool, set_experiment, set_gate, set_agent, set_runtime):
        wire(runtime.proxy_service)

    return uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.http_host,
            port=settings.http_port,
            log_level="warning",
            timeout_graceful_shutdown=settings.shutdown_grace_sec,
        )
    )


async def _serve_http_until(server: uvicorn.Server, shutdown: asyncio.Event) -> None:
    """run the http server until it stops on its own or shutdown is requested."""
    serving = asyncio.ensure_future(server.serve())
    stopping = asyncio.ensure_future(shutdown.wait())
    try:
        await asyncio.wait({serving, stopping}, return_when=asyncio.FIRST_COMPLETED)
        server.should_exit = True
        await serving
    finally:
        await drain(stopping)


async def _serve_grpc(settings: ProxySettings) -> None:
    async with shutdown_signal() as shutdown, ProxyRuntime(settings) as runtime:
        server = build_grpc_server(settings, runtime)
        logger.info(
            "starting proxy grpc server on %s:%s",
            settings.grpc_host,
            settings.grpc_port,
        )
        await server.start()
        await serve_until_shutdown(server, shutdown, grace=settings.shutdown_grace_sec)


async def _serve_http(settings: ProxySettings) -> None:
    async with shutdown_signal() as shutdown, ProxyRuntime(settings) as runtime:
        server = build_http_server(settings, runtime)
        logger.info(
            "starting proxy http server on %s:%s",
            settings.http_host,
            settings.http_port,
        )
        await _serve_http_until(server, shutdown)


async def _serve_both(settings: ProxySettings) -> None:
    async with shutdown_signal() as shutdown, ProxyRuntime(settings) as runtime:
        grpc_server = build_grpc_server(settings, runtime)
        http_server = build_http_server(settings, runtime)

        logger.info(
            "starting proxy grpc server on %s:%s",
            settings.grpc_host,
            settings.grpc_port,
        )
        logger.info(
            "starting proxy http server on %s:%s",
            settings.http_host,
            settings.http_port,
        )

        await grpc_server.start()
        try:
            await _serve_http_until(http_server, shutdown)
        finally:
            await grpc_server.stop(grace=settings.shutdown_grace_sec)


@click.group()
def cli():
    """proxy service cli."""
    configure_logging("proxy")


@cli.command()
@click.option("--host", default=None, help="grpc server host")
@click.option("--port", default=None, type=int, help="grpc server port")
def serve_grpc(host: str | None, port: int | None) -> None:
    """run grpc server only."""
    svc_settings = ProxySettings()
    if host:
        svc_settings.grpc_host = host
    if port:
        svc_settings.grpc_port = port
    asyncio.run(_serve_grpc(svc_settings))


@cli.command()
@click.option("--host", default=None, help="http server host")
@click.option("--port", default=None, type=int, help="http server port")
def serve_http(host: str | None, port: int | None) -> None:
    """run http server only."""
    svc_settings = ProxySettings()
    if host:
        svc_settings.http_host = host
    if port:
        svc_settings.http_port = port
    asyncio.run(_serve_http(svc_settings))


@cli.command()
@click.option("--grpc-host", default=None, help="grpc server host")
@click.option("--grpc-port", default=None, type=int, help="grpc server port")
@click.option("--http-host", default=None, help="http server host")
@click.option("--http-port", default=None, type=int, help="http server port")
def serve(
    grpc_host: str | None,
    grpc_port: int | None,
    http_host: str | None,
    http_port: int | None,
) -> None:
    """run both grpc and http servers."""
    svc_settings = ProxySettings()
    if grpc_host:
        svc_settings.grpc_host = grpc_host
    if grpc_port:
        svc_settings.grpc_port = grpc_port
    if http_host:
        svc_settings.http_host = http_host
    if http_port:
        svc_settings.http_port = http_port
    asyncio.run(_serve_both(svc_settings))


if __name__ == "__main__":
    cli()
