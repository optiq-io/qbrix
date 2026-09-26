import asyncio

import pytest
from unittest.mock import AsyncMock
from unittest.mock import Mock

from qbrixstore.event import FeedbackEvent
from qbrixstore.stream import topology

from cortexsvc import server as server_module


@pytest.fixture
def serving(monkeypatch):
    """run serve() in the background with its service and grpc server mocked.

    the mock server's wait_for_termination never returns, so nothing but a
    signal can end the serve loop — which is the whole point of these tests.
    """

    async def _start(settings):
        service = AsyncMock()

        server = Mock()
        server.add_insecure_port = Mock()
        server.add_generic_rpc_handlers = Mock()
        server.start = AsyncMock()
        server.stop = AsyncMock()
        server.wait_for_termination = AsyncMock(side_effect=asyncio.Event().wait)

        monkeypatch.setattr(server_module, "CortexService", Mock(return_value=service))
        monkeypatch.setattr(server_module, "build_server", Mock(return_value=server))

        task = asyncio.create_task(server_module.serve(settings))
        for _ in range(200):
            if server.start.await_count:
                return service, server, task
            await asyncio.sleep(0.005)
        task.cancel()
        raise AssertionError("serve() did not start the grpc server")

    return _start


@pytest.fixture
def tenant_id():
    """default tenant id for testing"""
    return "tenant-001"


@pytest.fixture
def mock_redis_client():
    """mock redis client for param storage and experiment retrieval."""
    client = AsyncMock()
    client.client = AsyncMock()
    client.client.ping = AsyncMock(return_value=True)
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.get_experiment = AsyncMock()
    client.get_params = AsyncMock()
    client.set_params = AsyncMock()
    return client


@pytest.fixture
def mock_stream_consumer():
    """mock redis stream consumer, shaped like the transport-only interface.

    reads return raw entries and claim_pending returns a (cursor, entries) pair;
    decoding belongs to StreamWorker.
    """
    consumer = AsyncMock()
    consumer.spec = topology.FEEDBACK
    consumer.group = "cortex"
    consumer.connect = AsyncMock()
    consumer.close = AsyncMock()
    consumer.consume = AsyncMock(return_value=[])
    consumer.ack = AsyncMock()
    consumer.claim_pending = AsyncMock(return_value=("0-0", []))
    return consumer


@pytest.fixture
def sample_feedback_event(tenant_id):
    """create a sample feedback event."""
    return FeedbackEvent(
        tenant_id=tenant_id,
        experiment_id="exp-001",
        request_id="req-001",
        arm_index=0,
        reward=1.0,
        context_id="ctx-001",
        context_vector=[0.5, 0.3, 0.2],
        context_metadata={"user": "test"},
        timestamp_ms=1234567890,
    )


@pytest.fixture
def sample_experiment_record():
    """create a sample experiment record from redis."""
    return {
        "id": "exp-001",
        "policy": "BetaTSPolicy",
        "policy_params": {},
        "pool": {
            "id": "pool-001",
            "arms": [
                {"id": "arm-0", "index": 0},
                {"id": "arm-1", "index": 1},
                {"id": "arm-2", "index": 2},
            ],
        },
    }


@pytest.fixture
def sample_beta_ts_params():
    """create sample beta thompson sampling params."""
    return {
        "num_arms": 3,
        "alpha": [1.0, 1.0, 1.0],
        "beta": [1.0, 1.0, 1.0],
        "T": [0, 0, 0],
    }
