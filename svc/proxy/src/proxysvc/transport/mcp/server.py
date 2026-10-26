from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from mcp.server import CacheHint
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from qbrixlog import get_logger

from proxysvc.config import ProxySettings
from proxysvc.service import ProxyService
from proxysvc.transport.mcp.tool import register
from proxysvc.transport.mcp.verifier import ConnectionVerifier
from proxysvc.transport.mcp.verifier import rate_limited

logger = get_logger(__name__)

MCP_PATH = "/mcp"
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
TOOLS_TTL_MS = 60 * 60 * 1000

_proxy_service: Optional[ProxyService] = None


def set_proxy_service(service: ProxyService) -> None:
    global _proxy_service
    _proxy_service = service


def get_proxy_service() -> ProxyService:
    if _proxy_service is None:
        raise RuntimeError("proxy service not initialized")
    return _proxy_service


def build_mcp(settings: ProxySettings) -> tuple[MCPServer, ASGIApp]:
    """a stateless mcp server and the asgi app that serves it behind a
    connection's token.

    a session manager runs once per server, so each mount builds its own.
    """
    verifier = ConnectionVerifier(get_proxy_service, settings.mcp_resource)
    server = MCPServer(
        "qbrix",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.public_origin),
            resource_server_url=AnyHttpUrl(settings.mcp_resource),
            validate_token_resource=False,
        ),
        cache_hints={"tools/list": CacheHint(ttl_ms=TOOLS_TTL_MS)},
        subscriptions=False,
    )
    register(server, settings, get_proxy_service)
    # the bearer token is the only credential, and a browser never attaches
    # it for another origin, so dns rebinding has nothing to ride on
    server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    app = AuthenticationMiddleware(
        AuthContextMiddleware(
            RequireAuthMiddleware(
                StreamableHTTPASGIApp(server.session_manager),
                [],
                build_resource_metadata_url(AnyHttpUrl(settings.mcp_resource)),
            )
        ),
        backend=BearerAuthBackend(verifier),
        on_error=rate_limited,
    )
    return server, app


def resource_metadata(settings: ProxySettings) -> Route:
    """rfc 9728 metadata for /mcp. it names the authorization server exactly as
    that server names itself as issuer, which clients compare byte for byte."""
    body = {
        "resource": settings.mcp_resource,
        "authorization_servers": [settings.public_origin],
        "bearer_methods_supported": ["header"],
        "resource_name": "qbrix",
    }

    async def metadata(request: Request) -> JSONResponse:
        return JSONResponse(body, headers={"Cache-Control": "public, max-age=3600"})

    return Route(METADATA_PATH, endpoint=metadata, methods=["GET"])


def mount(app: FastAPI, settings: ProxySettings) -> MCPServer:
    """serve /mcp and its protected resource metadata on the app."""
    server, asgi = build_mcp(settings)
    app.router.routes.append(Route(MCP_PATH, endpoint=asgi))
    app.router.routes.append(resource_metadata(settings))
    app.state.mcp = server
    return server


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[None]:
    """runs the mounted server's session manager for the app's lifetime."""
    server: MCPServer | None = getattr(app.state, "mcp", None)
    if server is None:
        yield
        return
    async with server.session_manager.run():
        logger.info("mcp server running")
        yield
