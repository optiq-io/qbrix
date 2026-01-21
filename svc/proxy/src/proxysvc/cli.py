import asyncio
import logging
from concurrent import futures

import click
import grpc
import uvicorn
from grpc_reflection.v1alpha import reflection

from qbrixproto import proxy_pb2
from qbrixproto import proxy_pb2_grpc
from qbrixproto import auth_pb2
from qbrixproto import auth_pb2_grpc

from qbrixstore.postgres.session import init_db
from qbrixstore.postgres.session import create_tables
from qbrixstore.redis.client import RedisClient
from qbrixstore.config import PostgresSettings
from qbrixstore.config import RedisSettings

from proxysvc.config import ProxySettings
from proxysvc.service import ProxyService
from proxysvc.server import ProxyGRPCServicer
from proxysvc.http.auth.service import AuthService
from proxysvc.http.auth.server import AuthGRPCServicer
from proxysvc.http.auth.operator import init_operators

logger = logging.getLogger(__name__)


async def init_services(
    settings: ProxySettings,
) -> tuple[ProxyService, AuthService, RedisClient]:
    """initialize all services."""
    pg_settings = PostgresSettings(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_database,
    )
    init_db(pg_settings)
    await create_tables()

    redis_settings = RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        db=settings.redis_db,
        stream_name=settings.stream_name,
    )
    redis = RedisClient(redis_settings)
    await redis.connect()

    proxy_service = ProxyService(settings)
    await proxy_service.start()

    auth_service = AuthService(redis)

    init_operators(auth_service)

    return proxy_service, auth_service, redis


async def _serve_grpc(settings: ProxySettings) -> None:
    """start grpc server only."""
    proxy_service, auth_service, redis = await init_services(settings)

    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))

    proxy_pb2_grpc.add_ProxyServiceServicer_to_server(
        ProxyGRPCServicer(proxy_service), server
    )
    auth_pb2_grpc.add_AuthServiceServicer_to_server(
        AuthGRPCServicer(auth_service), server
    )

    service_names = (
        proxy_pb2.DESCRIPTOR.services_by_name["ProxyService"].full_name,
        auth_pb2.DESCRIPTOR.services_by_name["AuthService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    listen_addr = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    logger.info(f"starting proxy grpc server on {listen_addr}")
    await server.start()

    try:
        await server.wait_for_termination()
    finally:
        await proxy_service.stop()
        await redis.close()
        await server.stop(grace=5)


async def _serve_http(settings: ProxySettings) -> None:
    """start http server only."""
    proxy_service, auth_service, redis = await init_services(settings)

    from proxysvc.http.app import app
    from proxysvc.http.router.pool import set_proxy_service as set_pool_service
    from proxysvc.http.router.experiment import (
        set_proxy_service as set_experiment_service,
    )
    from proxysvc.http.router.gate import set_proxy_service as set_gate_service
    from proxysvc.http.router.agent import set_proxy_service as set_agent_service

    set_pool_service(proxy_service)
    set_experiment_service(proxy_service)
    set_gate_service(proxy_service)
    set_agent_service(proxy_service)

    config = uvicorn.Config(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    logger.info(
        f"starting proxy http server on {settings.http_host}:{settings.http_port}"
    )

    try:
        await server.serve()
    finally:
        await proxy_service.stop()
        await redis.close()


async def serve_both(settings: ProxySettings) -> None:
    """start both grpc and http servers concurrently."""
    proxy_service, auth_service, redis = await init_services(settings)

    # grpc server setup
    grpc_server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))

    proxy_pb2_grpc.add_ProxyServiceServicer_to_server(
        ProxyGRPCServicer(proxy_service), grpc_server
    )
    auth_pb2_grpc.add_AuthServiceServicer_to_server(
        AuthGRPCServicer(auth_service), grpc_server
    )

    service_names = (
        proxy_pb2.DESCRIPTOR.services_by_name["ProxyService"].full_name,
        auth_pb2.DESCRIPTOR.services_by_name["AuthService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, grpc_server)

    grpc_addr = f"{settings.grpc_host}:{settings.grpc_port}"
    grpc_server.add_insecure_port(grpc_addr)

    # http server setup
    from proxysvc.http.app import app
    from proxysvc.http.router.pool import set_proxy_service as set_pool_service
    from proxysvc.http.router.experiment import (
        set_proxy_service as set_experiment_service,
    )
    from proxysvc.http.router.gate import set_proxy_service as set_gate_service
    from proxysvc.http.router.agent import set_proxy_service as set_agent_service

    set_pool_service(proxy_service)
    set_experiment_service(proxy_service)
    set_gate_service(proxy_service)
    set_agent_service(proxy_service)

    http_config = uvicorn.Config(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_level="info",
    )
    http_server = uvicorn.Server(http_config)

    logger.info(f"starting proxy grpc server on {grpc_addr}")
    logger.info(
        f"starting proxy http server on {settings.http_host}:{settings.http_port}"
    )

    await grpc_server.start()

    try:
        await http_server.serve()
    finally:
        await proxy_service.stop()
        await redis.close()
        await grpc_server.stop(grace=5)


@click.group()
def cli():
    """proxy service cli."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


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
    asyncio.run(serve_both(svc_settings))


if __name__ == "__main__":
    cli()
