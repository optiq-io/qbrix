from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable
from typing import Callable
from typing import Generic
from typing import Sequence
from typing import TypeVar

import redis.asyncio as redis

from qbrixstore.event import Event
from qbrixstore.event import EventDecodeError
from qbrixstore.redis.streams import RedisStreamConsumer

logger = logging.getLogger(__name__)

EventT = TypeVar("EventT", bound=Event)

Handler = Callable[[list[tuple[str, EventT]]], Awaitable[Sequence[str]]]

_BACKOFF_START_SEC = 0.5
_BACKOFF_MAX_SEC = 30.0
_STOP_TIMEOUT_SEC = 30.0

# a recovery sweep is bounded so a redis whose XAUTOCLAIM cursor never reaches
# "0-0" cannot hang startup. reaching this means something is wrong, not busy.
_MAX_RECOVERY_SWEEPS = 1_000


def _is_nogroup(error: Exception) -> bool:
    return isinstance(error, redis.ResponseError) and str(error).startswith("NOGROUP")


class StreamWorker(Generic[EventT]):
    """the consumer loop that every stream consumer shares.

    create the group, reclaim the PEL, then read → batch → hand to a handler →
    ack what the handler says to ack. the services differ only in *when* an
    entry may be acked, and that difference is the handler's return value
    rather than a flag:

        return the ids -> ack them now (trace: the rows are in clickhouse)
        return []      -> the handler owns the ack (cortex acks after training,
                          meter after stripe has accepted a whole bucket)

    ``flush_interval_sec`` decides when the handler is called:

        <= 0  on every read that produced anything, with no buffering
        >  0  once the buffer reaches ``batch_size`` *or* the interval elapses —
              and then **even with an empty batch**, so time-driven work can live
              in the handler. meter relies on this: a bucket has to be closed and
              emitted on schedule whether or not new selections arrived, or a
              tenant that goes quiet never gets its last bucket billed.

    a decode failure quarantines that one entry instead of the batch it arrived
    in. an entry that cannot be decoded will never decode, so redelivering it
    forever turns one bad publish into a stalled consumer — which is what all
    five hand-rolled loops did.

    setup (group, then PEL) is retried with the same backoff as reads until it
    succeeds, and redone when redis reports the group gone, so a service can
    start before redis is reachable and survives losing the stream key.
    """

    def __init__(
        self,
        consumer: RedisStreamConsumer,
        handler: Handler[EventT],
        *,
        batch_size: int = 100,
        block_ms: int = 100,
        flush_interval_sec: float = 0.0,
        stop_timeout_sec: float = _STOP_TIMEOUT_SEC,
    ) -> None:
        self._consumer = consumer
        self._handler = handler
        self._batch_size = max(1, batch_size)
        self._block_ms = block_ms
        self._flush_interval_sec = flush_interval_sec
        self._stop_timeout_sec = stop_timeout_sec
        self._name = f"{consumer.spec.name}/{consumer.group}"
        self._batch: list[tuple[str, EventT]] = []
        self._quarantined = 0
        self._recovered: set[str] = set()
        self._running = False
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def quarantined(self) -> int:
        """entries dropped as undecodable. non-zero warrants looking at a log."""
        return self._quarantined

    @property
    def buffered(self) -> int:
        return len(self._batch)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._wake.clear()
        self._task = asyncio.create_task(
            self._run(), name=f"stream-worker:{self._name}"
        )
        logger.info("%s: worker started", self._name)

    async def stop(self) -> None:
        """stop cooperatively, flushing whatever is still buffered.

        the buffer lives in memory only, so cancelling the task loses it — which
        is why this exists and why nothing should cancel the task directly. for
        trace the buffered entries may already have been deleted from the stream
        by cortex's ack, making this flush their last chance to be persisted.
        """
        self._running = False
        self._wake.set()
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=self._stop_timeout_sec)
        except asyncio.TimeoutError:
            logger.error(
                "%s: did not stop within %ss, cancelling (%d entries buffered)",
                self._name,
                self._stop_timeout_sec,
                len(self._batch),
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("%s: worker stopped", self._name)

    async def _run(self) -> None:
        backoff = _BACKOFF_START_SEC
        last_flush = time.monotonic()
        ready = False

        while self._running:
            try:
                if not ready:
                    await self._setup()
                    ready = True
                    last_flush = time.monotonic()

                entries = await self._consumer.consume(
                    batch_size=max(1, self._batch_size - len(self._batch)),
                    block_ms=self._block_ms,
                )
                self._batch.extend(await self._decode(entries))

                if self._should_flush(last_flush):
                    await self._flush()
                    last_flush = time.monotonic()

                backoff = _BACKOFF_START_SEC
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa
                if ready and _is_nogroup(e):
                    logger.error("%s: consumer group lost, recreating", self._name)
                    ready = False
                    continue
                await self._fail(e, ready, backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_SEC)

        await self._drain()

    async def _setup(self) -> None:
        await self._consumer.ensure_group()
        await self._recover_pending()

    async def _fail(self, error: Exception, ready: bool, backoff: float) -> None:
        if ready:
            logger.error("%s: %s", self._name, error)
        else:
            logger.error(
                "%s: setup failed, retrying in %ss: %s", self._name, backoff, error
            )
        await self._pause(backoff)

    async def _pause(self, delay: float) -> None:
        """sleep for ``delay``, cut short by stop() so shutdown never waits it out."""
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    def _should_flush(self, last_flush: float) -> bool:
        if self._flush_interval_sec <= 0:
            return bool(self._batch)
        if len(self._batch) >= self._batch_size:
            return True
        return time.monotonic() - last_flush >= self._flush_interval_sec

    async def _flush(self) -> None:
        """hand the batch over, ack what came back, then clear.

        the batch is cleared only once both have succeeded, so a handler that
        raises — a clickhouse outage, say — keeps its entries and retries them on
        the next pass instead of dropping them.
        """
        ack_ids = await self._handler(list(self._batch))
        await self._consumer.ack(list(ack_ids))
        self._batch.clear()

    async def _drain(self) -> None:
        if not self._batch:
            return
        try:
            await self._flush()
        except Exception as e:  # noqa
            logger.error(
                "%s: flush on stop failed, %d entries lost: %s",
                self._name,
                len(self._batch),
                e,
            )

    async def _decode(
        self, entries: list[tuple[str, dict]]
    ) -> list[tuple[str, EventT]]:
        event = self._consumer.spec.event
        decoded: list[tuple[str, EventT]] = []
        poison: list[str] = []

        for message_id, data in entries:
            try:
                decoded.append((message_id, event.from_dict(data)))
            except EventDecodeError as e:
                # only a declared decode failure is quarantined. anything else is
                # a bug in the decoder rather than a bad entry, and is left to the
                # retry loop, where it is loud instead of quietly dropping data.
                poison.append(message_id)
                self._quarantined += 1
                logger.error(
                    "%s: quarantined %s: %s | payload=%r",
                    self._name,
                    message_id,
                    e,
                    data,
                )

        if poison:
            await self._consumer.ack(poison)

        return decoded

    async def _recover_pending(self) -> None:
        """reclaim entries a previous incarnation read but never acked.

        XREADGROUP with ">" only returns undelivered entries, so without this
        anything read before a crash is stranded in the PEL permanently.

        the sweep stops when it stops seeing *new* ids, not when the cursor comes
        back as "0-0". redis resets the cursor once the scan completes, but the
        entries are still pending for a handler that defers its ack (cortex,
        meter), so a rescan can legitimately return them again — and fakeredis's
        cursor is inclusive and never resets at all. tracking ids terminates
        correctly under both.

        the ids outlive a single call because setup is retried: a sweep that
        failed halfway has already handed entries to a handler that may defer
        their ack, and claiming them again would train or bill them twice.
        """
        seen: set[str] = set()
        before = len(self._recovered)
        cursor = "0-0"

        for _ in range(_MAX_RECOVERY_SWEEPS):
            cursor, entries = await self._consumer.claim_pending(
                count=self._batch_size, start_id=cursor
            )
            fresh = [(mid, data) for mid, data in entries if mid not in seen]
            seen.update(mid for mid, _ in entries)

            owed = [(mid, data) for mid, data in fresh if mid not in self._recovered]
            if owed:
                self._batch.extend(await self._decode(owed))
                self._recovered.update(mid for mid, _ in owed)
                if len(self._batch) >= self._batch_size:
                    await self._flush()

            if not fresh or cursor == "0-0":
                break
        else:
            logger.error("%s: pending recovery did not complete", self._name)

        if self._batch:
            await self._flush()

        recovered = len(self._recovered) - before
        if recovered:
            logger.info("%s: recovered %d pending entries", self._name, recovered)
