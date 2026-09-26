import asyncio
import os
import signal

import pytest
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import grpc
from qbrixproto import cortex_pb2
from qbrixproto import common_pb2

from cortexsvc.config import CortexSettings
from cortexsvc.server import CortexGRPCServicer


class TestCortexGRPCServicerInit:
    """test grpc servicer initialization."""

    def test_init_stores_service(self):
        # arrange
        mock_service = Mock()

        # act
        servicer = CortexGRPCServicer(mock_service)

        # assert
        assert servicer._service is mock_service


class TestCortexGRPCServicerFlushBatch:
    """test flush batch rpc handler."""

    @pytest.mark.asyncio
    async def test_flush_batch_calls_service_flush_batch(self):
        # arrange
        mock_service = AsyncMock()
        mock_service.flush_batch = AsyncMock(return_value=10)
        servicer = CortexGRPCServicer(mock_service)

        request = cortex_pb2.FlushBatchRequest(experiment_id="exp-001")
        context = Mock()

        # act
        response = await servicer.FlushBatch(request, context)

        # assert
        mock_service.flush_batch.assert_called_once_with("exp-001")
        assert response.events_processed == 10

    @pytest.mark.asyncio
    async def test_flush_batch_with_empty_experiment_id_passes_none(self):
        # arrange
        mock_service = AsyncMock()
        mock_service.flush_batch = AsyncMock(return_value=5)
        servicer = CortexGRPCServicer(mock_service)

        request = cortex_pb2.FlushBatchRequest(experiment_id="")
        context = Mock()

        # act
        response = await servicer.FlushBatch(request, context)

        # assert
        mock_service.flush_batch.assert_called_once_with(None)
        assert response.events_processed == 5

    @pytest.mark.asyncio
    async def test_flush_batch_handles_errors_gracefully(self):
        # arrange
        mock_service = AsyncMock()
        mock_service.flush_batch = AsyncMock(side_effect=Exception("flush error"))
        servicer = CortexGRPCServicer(mock_service)

        request = cortex_pb2.FlushBatchRequest(experiment_id="exp-001")
        context = Mock()

        # act
        response = await servicer.FlushBatch(request, context)

        # assert
        context.set_code.assert_called_once_with(grpc.StatusCode.INTERNAL)
        context.set_details.assert_called_once()
        assert response.events_processed == 0


class TestCortexGRPCServicerGetStats:
    """test get stats rpc handler."""

    @pytest.mark.asyncio
    async def test_get_stats_returns_all_experiments(self):
        # arrange
        mock_service = Mock()
        mock_service.get_stats = Mock(
            return_value=[
                {
                    "experiment_id": "exp-001",
                    "total": 100,
                    "pending": 5,
                    "last_train": 1234567890,
                },
                {
                    "experiment_id": "exp-002",
                    "total": 50,
                    "pending": 0,
                    "last_train": 1234567891,
                },
            ]
        )
        servicer = CortexGRPCServicer(mock_service)

        request = cortex_pb2.GetStatsRequest(experiment_id="")
        context = Mock()

        # act
        response = await servicer.GetStats(request, context)

        # assert
        mock_service.get_stats.assert_called_once_with(None)
        assert len(response.stats) == 2
        assert response.stats[0].experiment_id == "exp-001"
        assert response.stats[0].total_events == 100
        assert response.stats[0].pending_events == 5
        assert response.stats[0].last_train_timestamp_ms == 1234567890

    @pytest.mark.asyncio
    async def test_get_stats_with_experiment_id(self):
        # arrange
        mock_service = Mock()
        mock_service.get_stats = Mock(
            return_value=[
                {
                    "experiment_id": "exp-001",
                    "total": 75,
                    "pending": 2,
                    "last_train": 9876543210,
                }
            ]
        )
        servicer = CortexGRPCServicer(mock_service)

        request = cortex_pb2.GetStatsRequest(experiment_id="exp-001")
        context = Mock()

        # act
        response = await servicer.GetStats(request, context)

        # assert
        mock_service.get_stats.assert_called_once_with("exp-001")
        assert len(response.stats) == 1
        assert response.stats[0].experiment_id == "exp-001"

    @pytest.mark.asyncio
    async def test_get_stats_with_missing_fields_uses_defaults(self):
        # arrange
        mock_service = Mock()
        mock_service.get_stats = Mock(
            return_value=[
                {
                    "experiment_id": "exp-001"
                    # missing total, pending, last_train
                }
            ]
        )
        servicer = CortexGRPCServicer(mock_service)

        request = cortex_pb2.GetStatsRequest(experiment_id="exp-001")
        context = Mock()

        # act
        response = await servicer.GetStats(request, context)

        # assert
        assert response.stats[0].total_events == 0
        assert response.stats[0].pending_events == 0
        assert response.stats[0].last_train_timestamp_ms == 0


class TestCortexGRPCServicerHealth:
    """test health check rpc handler."""

    @pytest.mark.asyncio
    async def test_health_returns_serving_when_healthy(self):
        # arrange
        mock_service = AsyncMock()
        mock_service.health = AsyncMock(return_value=True)
        servicer = CortexGRPCServicer(mock_service)

        request = common_pb2.HealthCheckRequest()
        context = Mock()

        # act
        response = await servicer.Health(request, context)

        # assert
        assert response.status == common_pb2.HealthCheckResponse.SERVING

    @pytest.mark.asyncio
    async def test_health_returns_not_serving_when_unhealthy(self):
        # arrange
        mock_service = AsyncMock()
        mock_service.health = AsyncMock(return_value=False)
        servicer = CortexGRPCServicer(mock_service)

        request = common_pb2.HealthCheckRequest()
        context = Mock()

        # act
        response = await servicer.Health(request, context)

        # assert
        assert response.status == common_pb2.HealthCheckResponse.NOT_SERVING


class TestServeFunction:
    """serve() has to reach its teardown when the process is signalled.

    cortex owns its StreamWorker, so service.stop() is what drains
    feedback that has been read but not yet trained on. a serve() that never
    returns from wait_for_termination() makes that unreachable.
    """

    @pytest.mark.asyncio
    async def test_sigterm_runs_teardown(self, serving):
        service, server, task = await serving(CortexSettings())

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        service.stop.assert_awaited_once()
        server.stop.assert_awaited_once_with(grace=20)

    @pytest.mark.asyncio
    async def test_sigint_runs_teardown(self, serving):
        service, server, task = await serving(CortexSettings())

        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.wait_for(task, timeout=5)

        service.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_grpc_stops_before_the_service(self, serving):
        """in-flight rpcs must finish before their redis client is closed."""
        order = []
        service, server, task = await serving(CortexSettings())
        server.stop.side_effect = lambda grace: order.append("server")
        service.stop.side_effect = lambda: order.append("service")

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        assert order == ["server", "service"]

    @pytest.mark.asyncio
    async def test_binds_the_configured_address(self, serving):
        _, server, task = await serving(
            CortexSettings(grpc_host="0.0.0.0", grpc_port=50099)
        )

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        server.add_insecure_port.assert_called_once_with("0.0.0.0:50099")

    @pytest.mark.asyncio
    async def test_defaults_to_the_cortex_port(self, serving):
        _, server, task = await serving(None)

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5)

        server.add_insecure_port.assert_called_once_with("0.0.0.0:50052")
