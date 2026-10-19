from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections import deque

from qbrixlog import get_logger
from qbrixstore.event import AuditEvent
from qbrixstore.event import FeedbackEvent
from qbrixstore.redis.streams import RedisStreamPublisher

from cortexsvc.trainer import BatchTrainer

logger = get_logger(__name__)

ExperimentKey = tuple[str, str]
Message = tuple[str, FeedbackEvent]

_RETRY_START_SEC = 0.5
_RETRY_MAX_SEC = 30.0


class TrainingDispatcher:
    """dispatches feedback events to per-experiment queues and coordinates
    a pool of async workers for parallel training.

    each experiment's entries are trained in stream order, which the learning
    record's ``last_id`` relies on: a batch that fails goes back to the head of
    its queue and is retried after a backoff, never overtaken by later entries.
    """

    def __init__(
        self,
        trainer: BatchTrainer,
        num_workers: int = 4,
        audit_publisher: RedisStreamPublisher | None = None,
    ):
        self._trainer = trainer
        self._num_workers = num_workers
        self._audit_publisher = audit_publisher

        # per-experiment pending entries: (tenant_id, experiment_id) → (message_id, event)
        self._experiment_queues: dict[ExperimentKey, deque[Message]] = {}

        # tracks which experiments currently have an active worker
        self._active_experiments: set[ExperimentKey] = set()

        # experiments waiting out a retry backoff, and the backoff they are on
        self._retry_timers: dict[ExperimentKey, asyncio.TimerHandle] = {}
        self._retry_delay: dict[ExperimentKey, float] = {}

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

        for timer in self._retry_timers.values():
            timer.cancel()
        self._retry_timers.clear()

        # signal all workers to wake up and exit
        for _ in self._workers:
            await self._work_queue.put(("__shutdown__", "__shutdown__"))

        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()

        logger.info("all training workers stopped")

    def dispatch(self, messages: list[Message]) -> None:
        """route incoming messages to per-experiment queues and signal workers."""
        enqueued_keys: set[ExperimentKey] = set()

        for message_id, event in messages:
            key = (event.tenant_id, event.experiment_id)
            self._experiment_queues.setdefault(key, deque()).append((message_id, event))
            stats_key = f"{key[0]}:{key[1]}"
            self._stats[stats_key]["pending"] += 1
            enqueued_keys.add(key)

        for key in enqueued_keys:
            self._signal(key)

    def _signal(self, key: ExperimentKey) -> None:
        """queue an experiment for training unless a worker or a backoff holds it."""
        if key not in self._active_experiments and key not in self._retry_timers:
            self._work_queue.put_nowait(key)

    def _retry_later(self, key: ExperimentKey) -> float:
        delay = self._retry_delay.get(key, _RETRY_START_SEC)
        self._retry_delay[key] = min(delay * 2, _RETRY_MAX_SEC)

        def _due() -> None:
            self._retry_timers.pop(key, None)
            if self._running:
                self._signal(key)

        self._retry_timers[key] = asyncio.get_running_loop().call_later(delay, _due)
        return delay

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
            error: Exception | None = None

            try:
                await self._train_and_ack(key, worker_id)
            except Exception as e:  # noqa
                error = e
            finally:
                self._active_experiments.discard(key)

            if error is not None:
                delay = self._retry_later(key)
                logger.error(
                    "worker %d: error training %s/%s, retrying in %ss: %s",
                    worker_id,
                    key[0],
                    key[1],
                    delay,
                    error,
                )
            elif self._experiment_queues.get(key):
                # more events arrived while we were training
                self._signal(key)

        logger.info("worker %d stopped", worker_id)

    async def _train_and_ack(self, key: ExperimentKey, worker_id: int) -> None:
        """train everything queued for the experiment; the trainer acks it in the
        same transaction that stores what was learned."""
        tenant_id, experiment_id = key
        pending = len(self._experiment_queues.get(key) or ())
        if not pending:
            return

        logger.debug(
            "worker %d: training %s/%s with %d events",
            worker_id,
            tenant_id,
            experiment_id,
            pending,
        )

        start_ms = int(time.time() * 1000)

        await self._publish_audit_event(
            name="training.batch.started",
            tenant_id=tenant_id,
            resource_id=experiment_id,
            payload={"event_count": pending},
        )

        count = await self._train_batch(key)

        duration_ms = int(time.time() * 1000) - start_ms

        await self._publish_audit_event(
            name="training.batch.completed",
            tenant_id=tenant_id,
            resource_id=experiment_id,
            payload={"event_count": count, "duration_ms": duration_ms},
        )

        logger.debug(
            "worker %d: completed %s/%s — %d events trained",
            worker_id,
            tenant_id,
            experiment_id,
            count,
        )

    async def _train_batch(self, key: ExperimentKey) -> int:
        """take the experiment's whole queue and train it, putting it back at the
        head if training fails. returns how many entries were taken."""
        queue = self._experiment_queues.get(key)
        if not queue:
            return 0

        batch = list(queue)
        queue.clear()
        tenant_id, experiment_id = key

        try:
            count = await self._trainer.train_experiment(
                tenant_id, experiment_id, batch
            )
        except Exception:
            queue.extendleft(reversed(batch))
            raise

        self._retry_delay.pop(key, None)

        stats_key = f"{tenant_id}:{experiment_id}"
        self._stats[stats_key]["total"] += count
        self._stats[stats_key]["pending"] -= len(batch)
        self._stats[stats_key]["last_train"] = int(time.time() * 1000)
        return count

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
        """force-train all queued events, optionally filtered."""
        flushed = 0

        for key in list(self._experiment_queues.keys()):
            t_id, e_id = key
            if tenant_id and t_id != tenant_id:
                continue
            if experiment_id and e_id != experiment_id:
                continue

            if not self._experiment_queues[key]:
                continue

            # wait if a worker is currently training this experiment
            while key in self._active_experiments:
                await asyncio.sleep(0.01)

            self._active_experiments.add(key)
            try:
                flushed += len(self._experiment_queues[key])
                await self._train_batch(key)
            finally:
                self._active_experiments.discard(key)

        return flushed
