import asyncio
import pytest
from unittest.mock import AsyncMock

from cortexsvc.dispatcher import TrainingDispatcher
from qbrixstore.event import FeedbackEvent


def _make_event(
    tenant_id: str = "tenant-001", experiment_id: str = "exp-001"
) -> FeedbackEvent:
    return FeedbackEvent(
        tenant_id=tenant_id,
        experiment_id=experiment_id,
        request_id="req-001",
        arm_index=0,
        reward=1.0,
        context_id="ctx-001",
        context_vector=[0.5, 0.3, 0.2],
        context_metadata={"user": "test"},
        timestamp_ms=1234567890,
    )


@pytest.fixture
def mock_trainer():
    trainer = AsyncMock()
    trainer.train_experiment = AsyncMock(return_value=1)
    return trainer


@pytest.fixture
def mock_consumer():
    consumer = AsyncMock()
    consumer.ack = AsyncMock()
    return consumer


@pytest.fixture
def dispatcher(mock_trainer, mock_consumer):
    return TrainingDispatcher(
        trainer=mock_trainer,
        consumer=mock_consumer,
        num_workers=2,
    )


class TestDispatcherDispatch:
    """test event routing to per-experiment queues."""

    def test_dispatch_creates_experiment_queue(self, dispatcher):
        event = _make_event()
        dispatcher.dispatch([("msg-1", event)])

        key = ("tenant-001", "exp-001")
        assert key in dispatcher._experiment_queues
        assert dispatcher._experiment_queues[key].qsize() == 1

    def test_dispatch_routes_to_correct_queues(self, dispatcher):
        event1 = _make_event(experiment_id="exp-001")
        event2 = _make_event(experiment_id="exp-002")

        dispatcher.dispatch([("msg-1", event1), ("msg-2", event2)])

        assert dispatcher._experiment_queues[("tenant-001", "exp-001")].qsize() == 1
        assert dispatcher._experiment_queues[("tenant-001", "exp-002")].qsize() == 1

    def test_dispatch_accumulates_events_for_same_experiment(self, dispatcher):
        event1 = _make_event()
        event2 = _make_event()

        dispatcher.dispatch([("msg-1", event1), ("msg-2", event2)])

        assert dispatcher._experiment_queues[("tenant-001", "exp-001")].qsize() == 2

    def test_dispatch_signals_work_queue(self, dispatcher):
        event = _make_event()
        dispatcher.dispatch([("msg-1", event)])

        assert dispatcher._work_queue.qsize() == 1

    def test_dispatch_does_not_double_signal_same_experiment(self, dispatcher):
        event1 = _make_event()
        event2 = _make_event()

        dispatcher.dispatch([("msg-1", event1), ("msg-2", event2)])

        # only one work item for the same experiment
        assert dispatcher._work_queue.qsize() == 1

    def test_dispatch_updates_pending_stats(self, dispatcher):
        event = _make_event()
        dispatcher.dispatch([("msg-1", event)])

        assert dispatcher._stats["tenant-001:exp-001"]["pending"] == 1


class TestDispatcherWorker:
    """test worker training and ACK behavior."""

    @pytest.mark.asyncio
    async def test_worker_trains_and_acks(
        self, dispatcher, mock_trainer, mock_consumer
    ):
        event = _make_event()
        dispatcher.dispatch([("msg-1", event)])

        await dispatcher.start()
        # give worker time to pick up and process
        await asyncio.sleep(0.1)
        await dispatcher.stop()

        mock_trainer.train_experiment.assert_called_once_with(
            "tenant-001", "exp-001", [event]
        )
        mock_consumer.ack.assert_called_once_with(["msg-1"])

    @pytest.mark.asyncio
    async def test_worker_trains_multiple_experiments_in_parallel(
        self, mock_trainer, mock_consumer
    ):
        dispatcher = TrainingDispatcher(
            trainer=mock_trainer,
            consumer=mock_consumer,
            num_workers=2,
        )

        # use an event to synchronize: both experiments should start before either finishes
        training_started = asyncio.Event()
        call_count = 0

        async def slow_train(tenant_id, experiment_id, events):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                training_started.set()
            await asyncio.sleep(0.05)
            return len(events)

        mock_trainer.train_experiment.side_effect = slow_train

        event1 = _make_event(experiment_id="exp-001")
        event2 = _make_event(experiment_id="exp-002")

        dispatcher.dispatch([("msg-1", event1), ("msg-2", event2)])

        await dispatcher.start()
        await asyncio.sleep(0.2)
        await dispatcher.stop()

        assert mock_trainer.train_experiment.call_count == 2

    @pytest.mark.asyncio
    async def test_worker_updates_stats_after_training(
        self, dispatcher, mock_trainer, mock_consumer
    ):
        mock_trainer.train_experiment.return_value = 3

        events = [_make_event() for _ in range(3)]
        messages = [(f"msg-{i}", ev) for i, ev in enumerate(events)]
        dispatcher.dispatch(messages)

        await dispatcher.start()
        await asyncio.sleep(0.1)
        await dispatcher.stop()

        stats = dispatcher.get_stats(tenant_id="tenant-001", experiment_id="exp-001")
        assert len(stats) == 1
        assert stats[0]["total"] == 3
        assert stats[0]["last_train"] > 0

    @pytest.mark.asyncio
    async def test_worker_handles_training_error(
        self, dispatcher, mock_trainer, mock_consumer
    ):
        mock_trainer.train_experiment.side_effect = Exception("training failed")

        event = _make_event()
        dispatcher.dispatch([("msg-1", event)])

        await dispatcher.start()
        await asyncio.sleep(0.1)
        await dispatcher.stop()

        # should not crash; ACK should not be called on error
        mock_consumer.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_worker_requeues_when_more_events_arrive(
        self, dispatcher, mock_trainer, mock_consumer
    ):
        train_call_count = 0
        train_started = asyncio.Event()

        async def slow_train(tenant_id, experiment_id, events):
            nonlocal train_call_count
            train_call_count += 1
            if train_call_count == 1:
                train_started.set()
                await asyncio.sleep(0.05)
            return len(events)

        mock_trainer.train_experiment.side_effect = slow_train

        # dispatch first event
        event1 = _make_event()
        dispatcher.dispatch([("msg-1", event1)])

        await dispatcher.start()
        await train_started.wait()

        # dispatch second event while worker is training first
        event2 = _make_event()
        dispatcher.dispatch([("msg-2", event2)])

        await asyncio.sleep(0.2)
        await dispatcher.stop()

        # should have trained twice: once for msg-1, once for msg-2
        assert mock_trainer.train_experiment.call_count == 2


class TestDispatcherFlush:
    """test force flush behavior."""

    @pytest.mark.asyncio
    async def test_flush_trains_all_queued_events(
        self, dispatcher, mock_trainer, mock_consumer
    ):
        events = [_make_event() for _ in range(3)]
        messages = [(f"msg-{i}", ev) for i, ev in enumerate(events)]
        dispatcher.dispatch(messages)

        # flush without starting workers
        count = await dispatcher.flush()

        assert count == 3
        mock_trainer.train_experiment.assert_called_once()
        mock_consumer.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_filters_by_experiment(
        self, dispatcher, mock_trainer, mock_consumer
    ):
        event1 = _make_event(experiment_id="exp-001")
        event2 = _make_event(experiment_id="exp-002")

        dispatcher.dispatch([("msg-1", event1), ("msg-2", event2)])

        count = await dispatcher.flush(experiment_id="exp-001")

        assert count == 1
        mock_trainer.train_experiment.assert_called_once_with(
            "tenant-001", "exp-001", [event1]
        )

    @pytest.mark.asyncio
    async def test_flush_filters_by_tenant(
        self, dispatcher, mock_trainer, mock_consumer
    ):
        event1 = _make_event(tenant_id="tenant-001")
        event2 = _make_event(tenant_id="tenant-002")

        dispatcher.dispatch([("msg-1", event1), ("msg-2", event2)])

        count = await dispatcher.flush(tenant_id="tenant-001")

        assert count == 1

    @pytest.mark.asyncio
    async def test_flush_returns_zero_when_empty(self, dispatcher):
        count = await dispatcher.flush()
        assert count == 0


class TestDispatcherGetStats:
    """test stats retrieval."""

    def test_get_stats_returns_all(self, dispatcher):
        dispatcher._stats["tenant-001:exp-001"] = {
            "total": 10,
            "pending": 0,
            "last_train": 123,
        }
        dispatcher._stats["tenant-001:exp-002"] = {
            "total": 5,
            "pending": 2,
            "last_train": 456,
        }

        stats = dispatcher.get_stats()

        assert len(stats) == 2

    def test_get_stats_filters_by_experiment(self, dispatcher):
        dispatcher._stats["tenant-001:exp-001"] = {
            "total": 10,
            "pending": 0,
            "last_train": 123,
        }
        dispatcher._stats["tenant-001:exp-002"] = {
            "total": 5,
            "pending": 2,
            "last_train": 456,
        }

        stats = dispatcher.get_stats(tenant_id="tenant-001", experiment_id="exp-001")

        assert len(stats) == 1
        assert stats[0]["total"] == 10

    def test_get_stats_returns_empty_for_missing(self, dispatcher):
        stats = dispatcher.get_stats(tenant_id="tenant-001", experiment_id="exp-999")
        assert stats == []


class TestDispatcherLifecycle:
    """test start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_workers(self, dispatcher):
        await dispatcher.start()

        assert len(dispatcher._workers) == 2
        assert dispatcher._running is True

        await dispatcher.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_workers(self, dispatcher):
        await dispatcher.start()
        await dispatcher.stop()

        assert len(dispatcher._workers) == 0
        assert dispatcher._running is False
