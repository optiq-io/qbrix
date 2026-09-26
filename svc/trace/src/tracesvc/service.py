from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Callable
from typing import Sequence

from qbrixlog import get_logger
from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.clickhouse.migrations import create_tables
from qbrixstore.event import AuditEvent
from qbrixstore.event import Event
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.config import RedisSettings
from qbrixstore.config import ClickHouseSettings
from qbrixstore.stream import topology
from qbrixstore.stream.topology import StreamSpec
from qbrixstore.stream.worker import Handler
from qbrixstore.stream.worker import StreamWorker

from tracesvc.config import TraceSettings

logger = get_logger(__name__)

CONSUMER_GROUP = "trace"


class TraceService:
    """service for persisting selection, feedback and audit events to clickhouse.

    all three streams are consumed identically — accumulate a batch, insert it,
    ack it — so all three run on a StreamWorker and differ only in which insert
    they call and which counter they bump.
    """

    def __init__(self, settings: TraceSettings):
        self._settings = settings
        self._clickhouse: ClickHouseClient | None = None
        self._consumers: list[RedisStreamConsumer] = []
        self._workers: list[StreamWorker] = []
        self._stats: dict[str, dict] = defaultdict(
            lambda: {"selections": 0, "feedback": 0, "audit": 0, "last_write": 0}
        )
        self._running = False

    def _consumer(
        self, spec: StreamSpec, settings: RedisSettings
    ) -> RedisStreamConsumer:
        return RedisStreamConsumer(
            spec,
            CONSUMER_GROUP,
            settings=settings,
            consumer_name=self._settings.consumer_name,
        )

    async def _start_worker(
        self, spec: StreamSpec, settings: RedisSettings, handler: Handler
    ) -> None:
        consumer = self._consumer(spec, settings)
        await consumer.connect()
        worker = StreamWorker(
            consumer,
            handler,
            batch_size=self._settings.batch_size,
            block_ms=100,
            flush_interval_sec=self._settings.flush_interval_sec,
            stop_timeout_sec=self._settings.shutdown_grace_sec,
        )
        await worker.start()
        self._consumers.append(consumer)
        self._workers.append(worker)
        logger.info("%s consumer started: %s", spec.name, self._settings.consumer_name)

    async def start(self) -> None:
        clickhouse_settings = ClickHouseSettings(
            host=self._settings.clickhouse_host,
            port=self._settings.clickhouse_port,
            user=self._settings.clickhouse_user,
            password=self._settings.clickhouse_password,
            database=self._settings.clickhouse_database,
        )
        self._clickhouse = ClickHouseClient(clickhouse_settings)
        self._clickhouse.connect()
        logger.info(
            "connected to clickhouse at %s:%s",
            self._settings.clickhouse_host,
            self._settings.clickhouse_port,
        )

        create_tables(
            self._clickhouse.client
        )  # attention: ttl days need to be configurable, defaults to 90
        logger.info("clickhouse tables initialized")

        redis_settings = RedisSettings(
            host=self._settings.redis_host,
            port=self._settings.redis_port,
            password=self._settings.redis_password,
            db=self._settings.redis_db,
        )

        await self._start_worker(
            topology.SELECTION, redis_settings, self._handle_selection
        )
        await self._start_worker(
            topology.FEEDBACK, redis_settings, self._handle_feedback
        )
        await self._start_worker(topology.AUDIT, redis_settings, self._handle_audit)

        self._running = True

    async def stop(self) -> None:
        self._running = False

        # each worker drains its buffer through its handler before returning.
        # that drain is the only thing between buffered rows and losing them: they
        # are memory-only, and on qbrix:feedback cortex's ack may already have
        # deleted them from the stream.
        #
        # concurrently, because the three drains are independent and a pod's
        # termination grace has to cover them: in sequence they would cost three
        # stop timeouts, not one.
        await asyncio.gather(*(worker.stop() for worker in self._workers))
        for consumer in self._consumers:
            await consumer.close()
        self._workers = []
        self._consumers = []

        if self._clickhouse:
            self._clickhouse.close()

        logger.info("trace service stopped")

    async def _persist(
        self,
        batch: list[tuple[str, Event]],
        insert: Callable[[list], None],
        counter: str,
        label: str,
        stats_key: Callable[[Event], str],
    ) -> Sequence[str]:
        """insert the batch, then hand the ids back for the worker to ack.

        the worker calls this on every flush boundary, so an empty batch is
        routine rather than exceptional.
        """
        if not batch:
            return ()

        events = [event for _, event in batch]
        insert(events)

        written_at = int(time.time() * 1000)
        for event in events:
            stats = self._stats[stats_key(event)]
            stats[counter] += 1
            stats["last_write"] = written_at

        logger.info("persisted %d %s events", len(events), label)
        return [message_id for message_id, _ in batch]

    async def _handle_selection(
        self, batch: list[tuple[str, SelectionEvent]]
    ) -> Sequence[str]:
        return await self._persist(
            batch,
            self._clickhouse.insert_selection_events,
            "selections",
            "selection",
            lambda event: f"{event.tenant_id}:{event.experiment_id}",
        )

    async def _handle_feedback(
        self, batch: list[tuple[str, FeedbackEvent]]
    ) -> Sequence[str]:
        return await self._persist(
            batch,
            self._clickhouse.insert_feedback_events,
            "feedback",
            "feedback",
            lambda event: f"{event.tenant_id}:{event.experiment_id}",
        )

    async def _handle_audit(self, batch: list[tuple[str, AuditEvent]]) -> Sequence[str]:
        return await self._persist(
            batch,
            self._clickhouse.insert_audit_events,
            "audit",
            "audit",
            lambda event: f"{event.tenant_id}:audit",
        )

    def get_stats(
        self, tenant_id: str | None = None, experiment_id: str | None = None
    ) -> list[dict]:
        """get stats, optionally filtered by tenant_id and/or experiment_id."""
        if tenant_id and experiment_id:
            stats_key = f"{tenant_id}:{experiment_id}"
            stats = self._stats.get(stats_key)
            if stats:
                return [
                    {"tenant_id": tenant_id, "experiment_id": experiment_id, **stats}
                ]
            return []

        results = []
        for key, stats in self._stats.items():
            parts = key.split(":", 1)
            if len(parts) == 2:
                t_id, e_id = parts
                if tenant_id and t_id != tenant_id:
                    continue
                if experiment_id and e_id != experiment_id:
                    continue
                results.append({"tenant_id": t_id, "experiment_id": e_id, **stats})
        return results

    async def health(self) -> bool:
        try:
            return self._clickhouse.health_check()
        except Exception:  # noqa
            return False
