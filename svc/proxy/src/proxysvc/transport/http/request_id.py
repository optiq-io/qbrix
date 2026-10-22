from __future__ import annotations

from starlette.types import ASGIApp
from starlette.types import Message
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from qbrixlog.context import request_context

from proxysvc.core.actor import inbound_request_id

REQUEST_ID_HEADER = "x-request-id"


class RequestIdMiddleware:
    """gives every request an id, in the logs, on any change it makes, and on
    the response. outermost, so every other middleware logs under it."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        inbound = None
        for name, value in scope["headers"]:
            if name == REQUEST_ID_HEADER.encode():
                inbound = value.decode("latin-1")
                break
        request_id = inbound_request_id(inbound)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        with request_context(request_id):
            await self._app(scope, receive, send_with_id)
