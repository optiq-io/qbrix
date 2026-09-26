from __future__ import annotations

import time
from typing import Sequence

from qbrixlog import get_logger
from qbrixstore.config import PostgresSettings
from qbrixstore.config import RedisSettings
from qbrixstore.postgres.session import init_db
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.event import SelectionEvent
from qbrixstore.stream import topology
from qbrixstore.stream.worker import StreamWorker

from metersvc.config import MeterSettings
from metersvc.customer import CustomerCache
from metersvc.emitter import MeterEmitter

logger = get_logger(__name__)

CONSUMER_GROUP = "metering"


class BucketAggregator:
    """sums selection counts per (tenant_id, wall-clock bucket).

    a bucket is derived from the event's own timestamp so the aggregation (and
    therefore the stripe idempotency identifier) is deterministic across replays
    and crashes. each bucket holds the stream message ids that fed it so they can
    be acked once — and only once — stripe has accepted the bucket's summed value.
    """

    def __init__(self, bucket_ms: int):
        self._bucket_ms = bucket_ms
        # (tenant_id, bucket) -> {"count": int, "message_ids": list[str]}
        self._buckets: dict[tuple[str, int], dict] = {}

    def add(self, message_id: str, event: SelectionEvent) -> None:
        bucket = event.timestamp_ms // self._bucket_ms
        key = (event.tenant_id, bucket)
        entry = self._buckets.get(key)
        if entry is None:
            entry = {"count": 0, "message_ids": []}
            self._buckets[key] = entry
        entry["count"] += 1
        entry["message_ids"].append(message_id)

    def closed_keys(self, now_ms: int, grace_ms: int) -> list[tuple[str, int]]:
        """keys whose bucket ended more than ``grace_ms`` ago, oldest first."""
        closed = []
        for tenant_id, bucket in self._buckets:
            bucket_end_ms = (bucket + 1) * self._bucket_ms
            if now_ms >= bucket_end_ms + grace_ms:
                closed.append((tenant_id, bucket))
        return sorted(closed, key=lambda k: k[1])

    def pop(self, key: tuple[str, int]) -> dict:
        return self._buckets.pop(key)

    def restore(self, key: tuple[str, int], entry: dict) -> None:
        """put a popped bucket back after a failed emit, so it retries later."""
        self._buckets[key] = entry

    def __len__(self) -> int:
        return len(self._buckets)


class MeterService:
    """consumes qbrix:selection and reports usage to a Stripe billing meter.

    SINGLE INSTANCE BY DESIGN. all replicas would share the ``metering`` consumer
    group, so redis would split a bucket's selections across them; each replica
    would emit a partial sum under the same ``tenant:bucket`` idempotency
    identifier, and stripe would dedup the partials — silently undercounting.
    a single consumer sees the whole bucket and emits one correct sum. the helm
    chart pins replicaCount=1 with no HPA for this reason.

    if this ever has to scale horizontally, shard the
    idempotency identifier by consumer (e.g. ``tenant:bucket:consumer``) so
    stripe SUMs the per-replica partials instead of deduping them — but reclaim
    across replicas makes that fragile, so single-instance is preferred for now.
    """

    def __init__(self, settings: MeterSettings):
        self._settings = settings
        self._consumer: RedisStreamConsumer | None = None
        self._worker: StreamWorker[SelectionEvent] | None = None
        self._emitter: MeterEmitter | None = None
        self._customers = CustomerCache(
            maxsize=settings.customer_cache_maxsize,
            ttl=settings.customer_cache_ttl_seconds,
        )
        self._aggregator = BucketAggregator(settings.bucket_ms)
        self._running = False

    async def start(self) -> None:
        init_db(
            PostgresSettings(
                host=self._settings.postgres_host,
                port=self._settings.postgres_port,
                user=self._settings.postgres_user,
                password=self._settings.postgres_password,
                database=self._settings.postgres_database,
            )
        )

        redis_settings = RedisSettings(
            host=self._settings.redis_host,
            port=self._settings.redis_port,
            password=self._settings.redis_password,
            db=self._settings.redis_db,
        )
        self._consumer = RedisStreamConsumer(
            topology.SELECTION,
            CONSUMER_GROUP,
            settings=redis_settings,
            consumer_name=self._settings.consumer_name,
        )
        await self._consumer.connect()

        self._emitter = MeterEmitter(
            self._settings.stripe_secret_key,
            self._settings.stripe_meter_event_name,
        )

        # the worker's flush interval *is* the emit interval: closing a bucket is
        # wall-clock work, so the handler has to run on schedule whether or not
        # selections arrived, or a tenant that goes quiet never has its last
        # bucket billed. keeping it in the handler also keeps aggregation and
        # emission on one task — a separate emit ticker could pop a bucket, await
        # stripe, and have the consume task recreate the same key underneath it,
        # which stripe would dedup into an undercount.
        self._worker = StreamWorker(
            self._consumer,
            self._handle,
            batch_size=self._settings.batch_size,
            block_ms=self._settings.block_ms,
            flush_interval_sec=self._settings.emit_interval_seconds,
            stop_timeout_sec=self._settings.shutdown_grace_sec,
        )
        await self._worker.start()

        self._running = True
        logger.info(
            "meter service started: stream=%s group=%s bucket=%ss",
            topology.SELECTION.name,
            CONSUMER_GROUP,
            self._settings.bucket_seconds,
        )

    async def _handle(self, batch: list[tuple[str, SelectionEvent]]) -> Sequence[str]:
        """aggregate, then close whatever is due.

        returns no ids: the ack belongs to _emit_bucket, once stripe has accepted
        the bucket's summed value. that is what makes a crash safe to replay.
        """
        for message_id, event in batch:
            self._aggregator.add(message_id, event)
        await self._emit_closed_buckets()
        return ()

    async def _emit_closed_buckets(self, now_ms: int | None = None) -> None:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        grace_ms = self._settings.close_grace_seconds * 1000

        for key in self._aggregator.closed_keys(now_ms, grace_ms):
            tenant_id, bucket = key
            try:
                await self._emit_bucket(tenant_id, bucket)
            except Exception as e:  # noqa
                # leave the bucket in place; it retries on the next pass.
                logger.error("error emitting bucket %s:%s: %s", tenant_id, bucket, e)

    async def _emit_bucket(self, tenant_id: str, bucket: int) -> None:
        entry = self._aggregator.pop((tenant_id, bucket))
        message_ids = entry["message_ids"]

        customer_id = await self._customers.get(tenant_id)
        if customer_id is None:
            # not a billable tenant (free / no subscription / no customer):
            # drop the messages, nothing to report.
            await self._consumer.ack(message_ids)
            return

        ok = self._emitter.emit(
            stripe_customer_id=customer_id,
            value=entry["count"],
            identifier=f"{tenant_id}:{bucket}",
            timestamp=(bucket + 1) * self._settings.bucket_seconds,
        )

        if ok:
            await self._consumer.ack(message_ids)
            logger.info(
                "reported %d selections for %s bucket %s",
                entry["count"],
                tenant_id,
                bucket,
            )
        else:
            # stripe rejected/errored — keep the bucket so it retries and stays
            # unacked (and thus safe in the stream) until stripe recovers.
            self._aggregator.restore((tenant_id, bucket), entry)

    async def stop(self) -> None:
        self._running = False
        if self._worker:
            await self._worker.stop()
        if self._consumer:
            await self._consumer.close()

    async def health(self) -> bool:
        return self._running
