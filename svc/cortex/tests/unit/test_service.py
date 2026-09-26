import asyncio
import pytest
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

from cortexsvc.config import CortexSettings
from cortexsvc.service import CortexService
from qbrixstore.event import FeedbackEvent


class TestCortexServiceInit:
    """test cortex service initialization."""

    def test_init_stores_settings(self):
        settings = CortexSettings(redis_host="test-redis", redis_port=6380)

        service = CortexService(settings)

        assert service._settings is settings
        assert service._redis is None
        assert service._consumer is None
        assert service._trainer is None
        assert service._dispatcher is None
        assert service._running is False


class TestCortexServiceStart:
    """test service startup."""

    @pytest.mark.asyncio
    async def test_start_connects_to_redis(
        self, mock_redis_client, mock_stream_consumer
    ):
        settings = CortexSettings()
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                mock_redis_client.connect.assert_called_once()
                mock_stream_consumer.connect.assert_called_once()
                assert service._redis is mock_redis_client
                assert service._consumer is mock_stream_consumer
                assert service._running is True

                await service.stop()

    @pytest.mark.asyncio
    async def test_start_creates_dispatcher(
        self, mock_redis_client, mock_stream_consumer
    ):
        settings = CortexSettings(num_workers=2)
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                assert service._trainer is not None
                assert service._dispatcher is not None
                assert len(service._dispatcher._workers) == 2

                await service.stop()


class TestCortexServiceStop:
    """test service shutdown."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_to_false(
        self, mock_redis_client, mock_stream_consumer
    ):
        settings = CortexSettings()
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                await service.stop()

                assert service._running is False

    @pytest.mark.asyncio
    async def test_stop_closes_connections(
        self, mock_redis_client, mock_stream_consumer
    ):
        settings = CortexSettings()
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                await service.stop()

                mock_stream_consumer.close.assert_called_once()
                mock_redis_client.close.assert_called_once()


class TestCortexServiceHandler:
    """the seam StreamWorker drives.

    the loop itself — batching, PEL recovery, poison quarantine, backoff — belongs
    to the worker and is tested in lib/store/tests/test_worker.py. what is cortex's
    is that feedback reaches the dispatcher and that the ack is left to it.
    """

    @pytest.mark.asyncio
    async def test_handler_routes_feedback_to_the_dispatcher(
        self, mock_redis_client, mock_stream_consumer, sample_feedback_event
    ):
        service = CortexService(CortexSettings())

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                await service._handle([("msg-1", sample_feedback_event)])

                key = (
                    sample_feedback_event.tenant_id,
                    sample_feedback_event.experiment_id,
                )
                assert key in service._dispatcher._experiment_queues

                await service.stop()

    @pytest.mark.asyncio
    async def test_handler_defers_the_ack_to_the_dispatcher(
        self, mock_redis_client, mock_stream_consumer, sample_feedback_event
    ):
        """feedback must stay redeliverable until it has been trained on."""
        service = CortexService(CortexSettings())

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()
                mock_stream_consumer.ack.reset_mock()

                acked = await service._handle([("msg-1", sample_feedback_event)])

                assert list(acked) == []
                mock_stream_consumer.ack.assert_not_awaited()

                await service.stop()

    @pytest.mark.asyncio
    async def test_worker_does_not_buffer_feedback(
        self, mock_redis_client, mock_stream_consumer
    ):
        """a flush interval here would delay training by up to that interval.

        the dispatcher already batches per experiment downstream, so the worker
        hands over whatever a read produced immediately.
        """
        service = CortexService(CortexSettings())

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                assert service._worker._flush_interval_sec == 0

                await service.stop()

    @pytest.mark.asyncio
    async def test_stop_stops_the_worker_before_the_dispatcher(
        self, mock_redis_client, mock_stream_consumer
    ):
        """everything the worker has read has to reach the dispatcher before the
        dispatcher drains and acks."""
        service = CortexService(CortexSettings())

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()
                order = []
                worker_stop = service._worker.stop
                dispatcher_stop = service._dispatcher.stop

                async def _worker_stop():
                    order.append("worker")
                    await worker_stop()

                async def _dispatcher_stop():
                    order.append("dispatcher")
                    await dispatcher_stop()

                service._worker.stop = _worker_stop
                service._dispatcher.stop = _dispatcher_stop

                await service.stop()

                assert order == ["worker", "dispatcher"]


class TestCortexServiceFlushBatch:
    """test manual batch flushing via dispatcher."""

    @pytest.mark.asyncio
    async def test_flush_batch_returns_zero_when_no_dispatcher(self):
        settings = CortexSettings()
        service = CortexService(settings)

        count = await service.flush_batch()

        assert count == 0

    @pytest.mark.asyncio
    async def test_flush_batch_delegates_to_dispatcher(
        self, mock_redis_client, mock_stream_consumer, sample_feedback_event
    ):
        settings = CortexSettings()
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                # manually dispatch some events
                service._dispatcher.dispatch(
                    [
                        ("msg-1", sample_feedback_event),
                        ("msg-2", sample_feedback_event),
                    ]
                )

                count = await service.flush_batch()

                assert count == 2

                await service.stop()

    @pytest.mark.asyncio
    async def test_flush_batch_with_experiment_filter(
        self, mock_redis_client, mock_stream_consumer
    ):
        settings = CortexSettings()
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                event1 = FeedbackEvent(
                    tenant_id="tenant-001",
                    experiment_id="exp-001",
                    request_id="req-001",
                    arm_index=0,
                    reward=1.0,
                    context_id="ctx-001",
                    context_vector=[0.5],
                    context_metadata={},
                    timestamp_ms=1234567890,
                )
                event2 = FeedbackEvent(
                    tenant_id="tenant-001",
                    experiment_id="exp-002",
                    request_id="req-002",
                    arm_index=1,
                    reward=0.5,
                    context_id="ctx-002",
                    context_vector=[0.3],
                    context_metadata={},
                    timestamp_ms=1234567891,
                )

                service._dispatcher.dispatch([("msg-1", event1), ("msg-2", event2)])

                count = await service.flush_batch(experiment_id="exp-001")

                assert count == 1

                await service.stop()


class TestCortexServiceGetStats:
    """test stats retrieval via dispatcher."""

    @pytest.mark.asyncio
    async def test_get_stats_returns_empty_when_no_dispatcher(self):
        settings = CortexSettings()
        service = CortexService(settings)

        stats = service.get_stats()

        assert stats == []

    @pytest.mark.asyncio
    async def test_get_stats_delegates_to_dispatcher(
        self, mock_redis_client, mock_stream_consumer
    ):
        settings = CortexSettings()
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()

                service._dispatcher._stats["tenant-001:exp-001"] = {
                    "total": 10,
                    "pending": 0,
                    "last_train": 123,
                }

                stats = service.get_stats(
                    tenant_id="tenant-001", experiment_id="exp-001"
                )

                assert len(stats) == 1
                assert stats[0]["total"] == 10

                await service.stop()


class TestCortexServiceHealth:
    """test health check."""

    @pytest.mark.asyncio
    async def test_health_returns_true_when_redis_is_reachable(
        self, mock_redis_client, mock_stream_consumer
    ):
        settings = CortexSettings()
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()
                mock_redis_client.client.ping.return_value = True

                healthy = await service.health()

                assert healthy is True

                await service.stop()

    @pytest.mark.asyncio
    async def test_health_returns_false_when_redis_is_unreachable(
        self, mock_redis_client, mock_stream_consumer
    ):
        settings = CortexSettings()
        service = CortexService(settings)

        with patch("cortexsvc.service.RedisClient", return_value=mock_redis_client):
            with patch(
                "cortexsvc.service.RedisStreamConsumer",
                return_value=mock_stream_consumer,
            ):
                await service.start()
                mock_redis_client.client.ping.side_effect = Exception(
                    "connection error"
                )

                healthy = await service.health()

                assert healthy is False

                await service.stop()
