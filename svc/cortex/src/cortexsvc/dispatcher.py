from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from qbrixlog import get_logger
from qbrixstore.event import AuditEvent
from qbrixstore.event import FeedbackEvent
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.redis.streams import RedisStreamPublisher

from cortexsvc.trainer import BatchTrainer

logger = get_logger(__name__)

ExperimentKey = tuple[str, str]


class TrainingDispatcher:
    """dispatches feedback events to per-experiment queues and coordinates
    a pool of async workers for parallel training with ACK tracking."""

    def __init__(
        self,
        trainer: BatchTrainer,
        consumer: RedisStreamConsumer,
        num_workers: int = 4,
        audit_publisher: RedisStreamPublisher | None = None,
    ):
        self._trainer = trainer
        self._consumer = consumer
        self._num_workers = num_workers
        self._audit_publisher = audit_publisher

        # per-experiment event queues: (tenant_id, experiment_id) → queue of (message_id, event)
        self._experiment_queues: dict[
            ExperimentKey, asyncio.Queue[tuple[str, FeedbackEvent]]
        ] = {}

        # tracks which experiments currently have an active worker
        self._active_experiments: set[ExperimentKey] = set()

        # work queue: experiment keys ready to be picked up by workers
        self._work_queue: asyncio.Queue[ExperimentKey] = asyncio.Queue()

        # training stats per experiment
        self._stats: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "pending": 0, "last_train": 0}
        )

        self._workers: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        self._running = True
        for i in range(self._num_workers):
            task = asyncio.create_task(self._worker_loop(i))
            self._workers.append(task)
        logger.info("started %d training workers", self._num_workers)

    async def stop(self) -> None:
        self._running = False

        # signal all workers to wake up and exit
        for _ in self._workers:
            await self._work_queue.put(("__shutdown__", "__shutdown__"))

        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()

        logger.info("all training workers stopped")

    def dispatch(self, messages: list[tuple[str, FeedbackEvent]]) -> None:
        """route incoming messages to per-experiment queues and signal workers."""
        enqueued_keys: set[ExperimentKey] = set()

        for message_id, event in messages:
            key = (event.tenant_id, event.experiment_id)

            if key not in self._experiment_queues:
                self._experiment_queues[key] = asyncio.Queue()

            self._experiment_queues[key].put_nowait((message_id, event))
            stats_key = f"{key[0]}:{key[1]}"
            self._stats[stats_key]["pending"] += 1
            enqueued_keys.add(key)

        # signal work queue for experiments that aren't already being trained
        for key in enqueued_keys:
            if key not in self._active_experiments:
                self._work_queue.put_nowait(key)

    async def _worker_loop(self, worker_id: int) -> None:
        """worker loop that picks experiments from the work queue and trains them."""
        logger.info("worker %d started", worker_id)

        while self._running:
            try:
                key = await asyncio.wait_for(self._work_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if key == ("__shutdown__", "__shutdown__"):
                break

            # skip if another worker is already handling this experiment
            if key in self._active_experiments:
                continue

            self._active_experiments.add(key)

            try:
                await self._train_and_ack(key, worker_id)
            except Exception as e:  # noqa
                logger.error(
                    "worker %d: error training %s/%s: %s",
                    worker_id,
                    key[0],
                    key[1],
                    e,
                )
            finally:
                self._active_experiments.discard(key)

                # if more events arrived while we were training, re-queue
                if (
                    key in self._experiment_queues
                    and not self._experiment_queues[key].empty()
                ):
                    self._work_queue.put_nowait(key)

        logger.info("worker %d stopped", worker_id)

    async def _train_and_ack(self, key: ExperimentKey, worker_id: int) -> None:
        """drain the experiment queue, train, and ACK all consumed messages."""
        tenant_id, experiment_id = key
        queue = self._experiment_queues.get(key)
        if queue is None or queue.empty():
            return

        # drain all currently queued events for this experiment
        events: list[FeedbackEvent] = []
        message_ids: list[str] = []

        while not queue.empty():
            try:
                message_id, event = queue.get_nowait()
                events.append(event)
                message_ids.append(message_id)
            except asyncio.QueueEmpty:
                break

        if not events:
            return

        logger.debug(
            "worker %d: training %s/%s with %d events",
            worker_id,
            tenant_id,
            experiment_id,
            len(events),
        )

        start_ms = int(time.time() * 1000)

        await self._publish_audit_event(
            name="training.batch.started",
            tenant_id=tenant_id,
            resource_id=experiment_id,
            payload={"event_count": len(events)},
        )

        count = await self._trainer.train_experiment(tenant_id, experiment_id, events)

        # ack all messages that were trained
        await self._consumer.ack(message_ids)

        duration_ms = int(time.time() * 1000) - start_ms

        # update stats
        stats_key = f"{tenant_id}:{experiment_id}"
        self._stats[stats_key]["total"] += count
        self._stats[stats_key]["pending"] -= len(events)
        self._stats[stats_key]["last_train"] = int(time.time() * 1000)

        await self._publish_audit_event(
            name="training.batch.completed",
            tenant_id=tenant_id,
            resource_id=experiment_id,
            payload={"event_count": count, "duration_ms": duration_ms},
        )

        logger.debug(
            "worker %d: completed %s/%s — %d events trained, %d acked",
            worker_id,
            tenant_id,
            experiment_id,
            count,
            len(message_ids),
        )

    async def _publish_audit_event(
        self,
        name: str,
        tenant_id: str,
        resource_id: str,
        payload: dict,
    ) -> None:
        """publish audit event for training lifecycle."""
        if not self._audit_publisher:
            return
        event = AuditEvent(
            name=name,
            tenant_id=tenant_id,
            actor_id="system",
            resource_type="training_batch",
            resource_id=resource_id,
            payload=payload,
            timestamp_ms=int(time.time() * 1000),
        )
        try:
            await self._audit_publisher.publish(event)
        except Exception as e:  # noqa
            logger.error("failed to publish audit event: %s", e)

    def get_stats(
        self, tenant_id: str | None = None, experiment_id: str | None = None
    ) -> list[dict]:
        """get training stats, optionally filtered."""
        if tenant_id and experiment_id:
            stats_key = f"{tenant_id}:{experiment_id}"
            stats = self._stats.get(stats_key)
            if stats:
                return [
                    {"tenant_id": tenant_id, "experiment_id": experiment_id, **stats}
                ]
            return []

        responses = []
        for key, stats in self._stats.items():
            parts = key.split(":", 1)
            if len(parts) == 2:
                t_id, e_id = parts
                if tenant_id and t_id != tenant_id:
                    continue
                if experiment_id and e_id != experiment_id:
                    continue
                responses.append({"tenant_id": t_id, "experiment_id": e_id, **stats})
        return responses

    async def flush(
        self, tenant_id: str | None = None, experiment_id: str | None = None
    ) -> int:
        """force-train and ACK all queued events, optionally filtered."""
        flushed = 0

        keys_to_flush = list(self._experiment_queues.keys())

        for key in keys_to_flush:
            t_id, e_id = key
            if tenant_id and t_id != tenant_id:
                continue
            if experiment_id and e_id != experiment_id:
                continue

            queue = self._experiment_queues[key]
            if queue.empty():
                continue

            # wait if a worker is currently training this experiment
            while key in self._active_experiments:
                await asyncio.sleep(0.01)

            self._active_experiments.add(key)
            try:
                events: list[FeedbackEvent] = []
                message_ids: list[str] = []
                while not queue.empty():
                    try:
                        mid, ev = queue.get_nowait()
                        events.append(ev)
                        message_ids.append(mid)
                    except asyncio.QueueEmpty:
                        break

                if events:
                    count = await self._trainer.train_experiment(t_id, e_id, events)
                    await self._consumer.ack(message_ids)

                    stats_key = f"{t_id}:{e_id}"
                    self._stats[stats_key]["total"] += count
                    self._stats[stats_key]["pending"] -= len(events)
                    self._stats[stats_key]["last_train"] = int(time.time() * 1000)
                    flushed += len(events)
            finally:
                self._active_experiments.discard(key)

        return flushed
