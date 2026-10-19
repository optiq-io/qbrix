"""boot a proxy process the way a self-hoster's container does, and report it.

run as a subprocess by `integration/test_oss_boot.py`: the edition is read from
the environment while modules import, and the http app is a module-level
singleton, so one interpreter can only ever hold one edition. what a *fresh*
process loads and mounts is exactly the thing no in-suite fixture can show.

it lives in its own directory because a script's own directory leads sys.path,
and `integration/` contains an `http` package that would shadow the stdlib one.

prints one json object: the mounted route paths, the grpc services the server
reflects, and which of the optional dependencies reached `sys.modules`.
"""

from __future__ import annotations

import asyncio
import json
import sys

import grpc
import redis.asyncio
from fakeredis.aioredis import FakeRedis
from fastapi.routing import iter_route_contexts
from grpc_reflection.v1alpha import reflection_pb2
from grpc_reflection.v1alpha import reflection_pb2_grpc

# every redis connection in the tree is opened through this one call, so the
# boot needs no server; the grpc channels to motor and cortex are lazy already.
redis.asyncio.from_url = lambda url, **kwargs: FakeRedis(**kwargs)

# the optional dependencies whose presence tells the edition apart: the cloud
# plugin and stripe belong to PROXY_EE_ENABLED, clickhouse to the analytics
# switch. each must be absent unless its switch asked for it.
OPTIONAL = ("proxysvc.ee", "stripe", "clickhouse_connect")


async def reflected_services(server: grpc.aio.Server, port: int) -> list[str]:
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = reflection_pb2_grpc.ServerReflectionStub(channel)
            request = reflection_pb2.ServerReflectionRequest(list_services="")
            async for response in stub.ServerReflectionInfo(iter([request])):
                return sorted(s.name for s in response.list_services_response.service)
    finally:
        await server.stop(grace=None)
    return []


async def probe() -> dict:
    from proxysvc.cli import build_grpc_server
    from proxysvc.config import settings
    from proxysvc.runtime import ProxyRuntime

    runtime = ProxyRuntime(settings)
    await runtime.start()

    # imported after start(), as cli.build_http_server does
    from proxysvc.transport.http.app import app

    routes = sorted(
        {route.path for route in iter_route_contexts(app.routes) if route.path}
    )
    # reflection sits behind the auth interceptor, which dev mode bypasses. only
    # the grpc server gets the dev copy: in dev the http app mounts /docs too.
    grpc_settings = settings.model_copy(update={"runenv": "dev"})
    grpc_services = await reflected_services(
        build_grpc_server(grpc_settings, runtime), settings.grpc_port
    )

    await runtime.stop()

    loaded = sorted(
        module
        for module in OPTIONAL
        if any(name == module or name.startswith(module + ".") for name in sys.modules)
    )
    return {"routes": routes, "grpc_services": grpc_services, "loaded": loaded}


print(json.dumps(asyncio.run(probe())))
