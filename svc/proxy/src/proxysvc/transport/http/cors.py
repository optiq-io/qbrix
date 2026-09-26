from __future__ import annotations

from typing import Any

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from proxysvc.config import ProxySettings
from proxysvc.config import settings
from proxysvc.transport.http.constant import AGENT_PATH_PREFIX

__all__ = [
    "ScopedCORSMiddleware",
    "console_origins",
    "CONSOLE_ORIGINS",
    "DEFAULT_CORS_POLICY",
    "AGENT_CORS_POLICY",
    "AGENT_CORS_PREFIXES",
]

LOCALHOST_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost",
]


def console_origins(config: ProxySettings) -> list[str]:
    """localhost keeps `make dev` working out of the box; a deployment serving
    the console on its own host adds it through PROXY_CORS_ORIGINS."""
    return LOCALHOST_ORIGINS + config.cors_origin_list


CONSOLE_ORIGINS = console_origins(settings)

DEFAULT_CORS_POLICY: dict[str, Any] = {
    "allow_origins": CONSOLE_ORIGINS,
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
    "expose_headers": ["Retry-After"],
}

# a customer calls select/feedback from their own domain, which we cannot
# enumerate. these endpoints authenticate by X-API-Key and never by cookie, so
# keeping credentials off is precisely what makes the wildcard origin safe —
# turning allow_credentials on here would make starlette echo the caller's
# origin instead, granting every site on the internet credentialed access.
AGENT_CORS_POLICY: dict[str, Any] = {
    "allow_origins": ["*"],
    "allow_credentials": False,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
    "expose_headers": ["Retry-After"],
    "max_age": 7200,
}

AGENT_CORS_PREFIXES = (AGENT_PATH_PREFIX,)


class ScopedCORSMiddleware:
    """applies one cors policy to a set of path prefixes and another to everything else.

    both branches are real CORSMiddleware instances so that preflight handling,
    origin matching and vary headers stay starlette's.
    """

    def __init__(
        self,
        app: ASGIApp,
        /,
        *,
        scoped_prefixes: tuple[str, ...],
        scoped_policy: dict[str, Any],
        default_policy: dict[str, Any],
    ) -> None:
        self.scoped_prefixes = tuple(scoped_prefixes)
        self.scoped = CORSMiddleware(app, **scoped_policy)
        self.default = CORSMiddleware(app, **default_policy)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(self.scoped_prefixes):
            await self.scoped(scope, receive, send)
            return

        await self.default(scope, receive, send)
