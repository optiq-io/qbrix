"""the served grpc server maps domain errors to status codes.

the interceptor's mapping is pinned in isolation elsewhere; these drive the
server `proxysvc.cli` actually builds, over a real channel.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import grpc
import pytest

from qbrixproto import auth_pb2
from qbrixproto import auth_pb2_grpc

from proxysvc.cli import build_grpc_server
from proxysvc.core.error import SignupClosedError


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def register_user(proxy_settings):
    auth_service = MagicMock()
    auth_service.register_user = AsyncMock()
    runtime = SimpleNamespace(proxy_service=MagicMock(), auth_service=auth_service)
    settings = proxy_settings.model_copy(
        update={"grpc_host": "127.0.0.1", "grpc_port": _free_port()}
    )
    server = build_grpc_server(settings, runtime)
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{settings.grpc_port}")
    stub = auth_pb2_grpc.AuthServiceStub(channel)
    request = auth_pb2.RegisterUserRequest(
        email="stranger@example.com", password="super-secret-123"
    )

    async def call(error: Exception) -> grpc.aio.AioRpcError:
        auth_service.register_user.side_effect = error
        with pytest.raises(grpc.aio.AioRpcError) as caught:
            await stub.RegisterUser(request)
        return caught.value

    yield call
    await channel.close()
    await server.stop(grace=None)


async def test_domain_error_reaches_the_client_as_its_status(register_user):
    err = await register_user(SignupClosedError("public registration is closed"))

    assert err.code() == grpc.StatusCode.PERMISSION_DENIED
    assert err.details() == "public registration is closed"
