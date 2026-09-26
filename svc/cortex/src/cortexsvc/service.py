from __future__ import annotations

from typing import Sequence

from qbrixlog import get_logger
from qbrixstore.event import FeedbackEvent
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.redis.streams import RedisStreamPublisher
from qbrixstore.config import RedisSettings
from qbrixstore.stream import topology
from qbrixstore.stream.worker import StreamWorker

from cortexsvc.config import CortexSettings
from cortexsvc.dispatcher import TrainingDispatcher
from cortexsvc.trainer import BatchTrainer

logger = get_logger(__name__)

CONSUMER_GROUP = "cortex"


class CortexService:

    def __init__(self, settings: CortexSettings):
        self._settings = settings
        self._redis: RedisClient | None = None
        self._consumer: RedisStreamConsumer | None = None
        self._worker: StreamWorker[FeedbackEvent] | None = None
        self._audit_publisher: RedisStreamPublisher | None = None
        self._trainer: BatchTrainer | None = None
        self._dispatcher: TrainingDispatcher | None = None
        self._running = False

    async def start(self) -> None:
        redis_settings = RedisSettings(
            host=self._settings.redis_host,
            port=self._settings.redis_port,
            password=self._settings.redis_password,
            db=self._settings.redis_db,
        )
        self._redis = RedisClient(redis_settings)
        await self._redis.connect()
        logger.info(
            "connected to redis at %s:%s",
            self._settings.redis_host,
            self._settings.redis_port,
        )

        self._consumer = RedisStreamConsumer(
            topology.FEEDBACK,
            CONSUMER_GROUP,
            settings=redis_settings,
            consumer_name=self._settings.consumer_name,
        )
        await self._consumer.connect()
        logger.info("stream consumer started: %s", self._settings.consumer_name)

        self._audit_publisher = RedisStreamPublisher(topology.AUDIT, redis_settings)
        await self._audit_publisher.connect()
        logger.info("audit publisher connected")

        self._trainer = BatchTrainer(self._redis)
        self._dispatcher = TrainingDispatcher(
            trainer=self._trainer,
            consumer=self._consumer,
            num_workers=self._settings.num_workers,
            audit_publisher=self._audit_publisher,
        )
        await self._dispatcher.start()

        # no flush interval: dispatch as soon as anything arrives, since the
        # dispatcher does its own per-experiment batching downstream and holding
        # feedback here would only add latency to training.
        self._worker = StreamWorker(
            self._consumer,
            self._handle,
            batch_size=self._settings.batch_size,
            block_ms=self._settings.batch_timeout_ms,
            flush_interval_sec=0,
            stop_timeout_sec=self._settings.shutdown_grace_sec,
        )
        await self._worker.start()

        self._running = True

    async def _handle(self, batch: list[tuple[str, FeedbackEvent]]) -> Sequence[str]:
        """hand feedback to the dispatcher.

        returns no ids: the dispatcher acks each experiment's messages once their
        training batch has been applied, so feedback stays redeliverable until it
        has actually been learned from.
        """
        self._dispatcher.dispatch(batch)
        return ()

    async def stop(self) -> None:
        self._running = False

        # the worker first, so everything it has read reaches the dispatcher
        # before the dispatcher drains and acks.
        if self._worker:
            await self._worker.stop()

        if self._dispatcher:
            await self._dispatcher.stop()

        if self._audit_publisher:
            await self._audit_publisher.close()
        if self._consumer:
            await self._consumer.close()
        if self._redis:
            await self._redis.close()
        logger.info("cortex service stopped")

    async def flush_batch(
        self, tenant_id: str | None = None, experiment_id: str | None = None
    ) -> int:
        """force flush queued events through the dispatcher."""
        if not self._dispatcher:
            return 0
        count = await self._dispatcher.flush(
            tenant_id=tenant_id, experiment_id=experiment_id
        )
        if count > 0:
            logger.info("force flushed %d events", count)
        return count

    def get_stats(
        self, tenant_id: str | None = None, experiment_id: str | None = None
    ) -> list[dict]:
        """get stats from the dispatcher."""
        if not self._dispatcher:
            return []
        return self._dispatcher.get_stats(
            tenant_id=tenant_id, experiment_id=experiment_id
        )

    async def health(self) -> bool:
        try:
            await self._redis.client.ping()
            return True
        except Exception:  # noqa
            return False
