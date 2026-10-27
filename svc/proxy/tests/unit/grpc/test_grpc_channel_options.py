"""The channel options the motor and cortex clients connect with."""

from __future__ import annotations

import time

import grpc
import pytest

from proxysvc.config import CortexClientSettings
from proxysvc.config import MotorClientSettings
from proxysvc.transport.grpc.client import CortexClient
from proxysvc.transport.grpc.client import MotorClient


@pytest.fixture
def channel_options(monkeypatch) -> list[dict]:
    created: list[dict] = []
    insecure_channel = grpc.aio.insecure_channel

    def record(target, options=None, **kwargs):
        created.append(dict(options or []))
        return insecure_channel(target, options=options, **kwargs)

    monkeypatch.setattr(grpc.aio, "insecure_channel", record)
    return created


@pytest.mark.parametrize("client_cls", [MotorClient, CortexClient])
async def test_channel_reconnects_within_seconds(channel_options, client_cls):
    client = client_cls("127.0.0.1:1")
    await client.connect()
    await client.close()

    (options,) = channel_options
    assert options["grpc.initial_reconnect_backoff_ms"] == 250
    assert options["grpc.min_reconnect_backoff_ms"] == 250
    assert options["grpc.max_reconnect_backoff_ms"] == 2000


@pytest.mark.parametrize(
    "client_cls, settings_cls",
    [(MotorClient, MotorClientSettings), (CortexClient, CortexClientSettings)],
)
async def test_reconnect_backoff_is_overridable(
    channel_options, client_cls, settings_cls
):
    settings = settings_cls(
        grpc_initial_reconnect_backoff_ms=100,
        grpc_min_reconnect_backoff_ms=50,
        grpc_max_reconnect_backoff_ms=500,
    )
    client = client_cls("127.0.0.1:1", settings)
    await client.connect()
    await client.close()

    (options,) = channel_options
    assert options["grpc.initial_reconnect_backoff_ms"] == 100
    assert options["grpc.min_reconnect_backoff_ms"] == 50
    assert options["grpc.max_reconnect_backoff_ms"] == 500


async def test_select_fails_fast_while_motor_is_down():
    client = MotorClient("127.0.0.1:1", MotorClientSettings(select_timeout_ms=500))
    await client.connect()
    started = time.perf_counter()

    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await client.select(
            tenant_id="t-1",
            experiment_id="exp-1",
            context_id="ctx-1",
            context_vector=[],
            context_metadata={},
        )

    await client.close()
    assert raised.value.code() == grpc.StatusCode.UNAVAILABLE
    assert time.perf_counter() - started < 0.5
