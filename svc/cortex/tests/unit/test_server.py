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
        mock_service.get_stats = Mock(return_value=[
            {
                "experiment_id": "exp-001",
                "total": 100,
                "pending": 5,
                "last_train": 1234567890
            },
            {
                "experiment_id": "exp-002",
                "total": 50,
                "pending": 0,
                "last_train": 1234567891
            }
        ])
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
        mock_service.get_stats = Mock(return_value=[
            {
                "experiment_id": "exp-001",
                "total": 75,
                "pending": 2,
                "last_train": 9876543210
            }
        ])
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
        mock_service.get_stats = Mock(return_value=[
            {
                "experiment_id": "exp-001"
                # missing total, pending, last_train
            }
        ])
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
    """test the serve function that starts the grpc server."""

    @pytest.mark.asyncio
    async def test_serve_with_custom_settings(self):
        # arrange
        settings = CortexSettings(
            grpc_host="0.0.0.0",
            grpc_port=50099,
            redis_host="test-redis"
        )

        mock_service = AsyncMock()
        mock_service.start = AsyncMock()
        mock_service.run_consumer = AsyncMock()
        mock_service.stop = AsyncMock()

        mock_server = AsyncMock()
        mock_server.add_insecure_port = Mock()
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()

        # simulate immediate termination
        async def wait_side_effect():
            pass

        mock_server.wait_for_termination = AsyncMock(side_effect=wait_side_effect)

        with patch("cortexsvc.server.CortexService", return_value=mock_service):
            with patch("cortexsvc.server.grpc.aio.server", return_value=mock_server):
                with patch("cortexsvc.server.cortex_pb2_grpc.add_CortexServiceServicer_to_server"):
                    with patch("cortexsvc.server.reflection.enable_server_reflection"):
                        # need to import here after patching
                        from cortexsvc.server import serve

                        # act
                        await serve(settings)

                        # assert
                        mock_service.start.assert_called_once()
                        mock_server.add_insecure_port.assert_called_once_with("0.0.0.0:50099")
                        mock_server.start.assert_called_once()
                        mock_service.stop.assert_called_once()
                        mock_server.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_serve_with_default_settings(self):
        # arrange
        mock_service = AsyncMock()
        mock_service.start = AsyncMock()
        mock_service.run_consumer = AsyncMock()
        mock_service.stop = AsyncMock()

        mock_server = AsyncMock()
        mock_server.add_insecure_port = Mock()
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()

        async def wait_side_effect():
            pass

        mock_server.wait_for_termination = AsyncMock(side_effect=wait_side_effect)

        with patch("cortexsvc.server.CortexService", return_value=mock_service):
            with patch("cortexsvc.server.grpc.aio.server", return_value=mock_server):
                with patch("cortexsvc.server.cortex_pb2_grpc.add_CortexServiceServicer_to_server"):
                    with patch("cortexsvc.server.reflection.enable_server_reflection"):
                        from cortexsvc.server import serve

                        # act
                        await serve(settings=None)

                        # assert
                        mock_service.start.assert_called_once()
                        mock_server.add_insecure_port.assert_called_once_with("0.0.0.0:50052")

    @pytest.mark.asyncio
    async def test_serve_cancels_consumer_task_on_shutdown(self):
        # arrange
        settings = CortexSettings()

        mock_service = AsyncMock()
        mock_service.start = AsyncMock()
        mock_service.stop = AsyncMock()

        # consumer that runs until cancelled
        async def long_running_consumer():
            try:
                while True:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                pass

        mock_service.run_consumer = long_running_consumer

        mock_server = AsyncMock()
        mock_server.add_insecure_port = Mock()
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()

        # simulate shutdown after brief wait
        async def wait_then_terminate():
            await asyncio.sleep(0.05)

        mock_server.wait_for_termination = AsyncMock(side_effect=wait_then_terminate)

        with patch("cortexsvc.server.CortexService", return_value=mock_service):
            with patch("cortexsvc.server.grpc.aio.server", return_value=mock_server):
                with patch("cortexsvc.server.cortex_pb2_grpc.add_CortexServiceServicer_to_server"):
                    with patch("cortexsvc.server.reflection.enable_server_reflection"):
                        from cortexsvc.server import serve
                        import asyncio

                        # act
                        await serve(settings)

                        # assert
                        mock_service.stop.assert_called_once()
                        mock_server.stop.assert_called_once_with(grace=5)
