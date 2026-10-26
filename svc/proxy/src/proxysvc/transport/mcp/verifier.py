from __future__ import annotations

from collections.abc import Callable

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from pydantic import ConfigDict
from starlette.authentication import AuthenticationError
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from qbrixlog.context import get_request_id

from proxysvc.core.error import ConnectionRateLimitedError
from proxysvc.core.error import ConnectionTokenInvalidError
from proxysvc.mod.connection.service import ConnectionPrincipal
from proxysvc.service import ProxyService


class ConnectionToken(AccessToken):
    """a connection's access token, with who it acts for."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    principal: ConnectionPrincipal


class RateLimited(AuthenticationError):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class ConnectionVerifier:
    """turns a bearer token into the connection it belongs to.

    every refusal reads the same, so a key, a revoked connection and a token
    for another resource are indistinguishable to the caller.
    """

    def __init__(self, service: Callable[[], ProxyService], resource: str):
        self._service = service
        self._resource = resource

    async def verify_token(self, token: str) -> ConnectionToken | None:
        try:
            principal = await self._service().connections.authenticate(
                token, request_id=get_request_id() or ""
            )
        except ConnectionTokenInvalidError:
            return None
        except ConnectionRateLimitedError as e:
            raise RateLimited(str(e), e.retry_after) from e
        return ConnectionToken(
            token=token,
            client_id=principal.actor.connection_id,
            scopes=[],
            resource=self._resource,
            subject=principal.actor.user_id,
            principal=principal,
        )


def rate_limited(conn: HTTPConnection, exc: AuthenticationError) -> JSONResponse:
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        {
            "error": "rate_limited",
            "error_description": (
                f"This connection made too many calls this minute. "
                f"Try again in {retry_after} seconds."
            ),
        },
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


def current_principal() -> ConnectionPrincipal:
    token = get_access_token()
    if not isinstance(token, ConnectionToken):
        raise RuntimeError("mcp tool called without a connection")
    return token.principal
