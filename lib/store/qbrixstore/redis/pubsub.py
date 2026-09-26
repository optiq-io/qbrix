import asyncio
import logging
from typing import AsyncIterator
from typing import Callable

import redis.asyncio as redis

from qbrixstore.config import RedisSettings

logger = logging.getLogger(__name__)

_BACKOFF_START_SEC = 0.5
_BACKOFF_MAX_SEC = 30.0


class RedisPubSubPublisher:
    """fan-out publisher: every subscriber receives every message.

    the counterpart to RedisStreamPublisher, for the opposite delivery shape.
    streams (with consumer groups) distribute each message to exactly one
    consumer, which is what a work queue wants; pub/sub delivers to all of
    them, which is what a broadcast wants.

    delivery is best-effort — a subscriber that is disconnected simply misses
    the message — so only send signals whose loss is recoverable, never state
    that cannot be re-derived from the database.
    """

    def __init__(self, channel: str, settings: RedisSettings | None = None):
        if settings is None:
            settings = RedisSettings()
        self._settings = settings
        self._channel = channel
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._settings.url, decode_responses=True)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def publish(self, message: str) -> int:
        """publish to the channel, returning the number of subscribers reached."""
        if self._client is None:
            raise RuntimeError("Publisher not connected. Call connect() first.")
        return await self._client.publish(self._channel, message)


class RedisPubSubConsumer:
    """fan-out consumer: receives every message published to the channel.

    unlike RedisStreamConsumer there is no consumer group, no ack and no
    pending list — a subscription is not shared between replicas, so each
    process sees every message rather than competing for it.

    holds its own connection because a subscribed redis connection cannot
    issue ordinary commands.

    reconnection is not handled here; BroadcastBus drives listen() in a retry
    loop, mirroring RedisStreamConsumer, whose consume() is likewise driven by
    a loop its owner supplies.
    """

    def __init__(self, channel: str, settings: RedisSettings | None = None):
        if settings is None:
            settings = RedisSettings()
        self._settings = settings
        self._channel = channel
        self._client: redis.Redis | None = None
        self._pubsub = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._settings.url, decode_responses=True)
        self._pubsub = self._client.pubsub()
        await self._pubsub.subscribe(self._channel)

    async def close(self) -> None:
        if self._pubsub:
            await self._pubsub.aclose()
            self._pubsub = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def listen(self) -> AsyncIterator[str]:
        """yield each message published to the channel.

        subscription confirmations are filtered out, so callers only ever see
        payloads.
        """
        if self._pubsub is None:
            raise RuntimeError("Consumer not connected. Call connect() first.")
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            yield data.decode() if isinstance(data, bytes) else str(data)


class BroadcastBus:
    """a channel every replica publishes to and subscribes to.

    pairs the publisher and consumer above with the retry loop and callback
    dispatch that every broadcast subscriber otherwise reimplements. bind a
    channel to it and register callbacks; start() subscribes for the process
    lifetime, publish() announces to the others.

    publishing dispatches locally first and does not wait on redis to do so,
    so the replica that made the change acts on it even if the broadcast fails.

    delivery is best-effort by construction: a subscriber that is disconnected
    misses the message, and there is no ack, no ordering and no replay. only
    send signals whose loss is recoverable — never state that cannot be
    re-derived from the database.
    """

    def __init__(self, channel: str, settings: RedisSettings | None = None):
        self._channel = channel
        self._publisher = RedisPubSubPublisher(channel, settings)
        self._consumer = RedisPubSubConsumer(channel, settings)
        self._callbacks: list[Callable[[str], None]] = []
        self._task: asyncio.Task | None = None

    def register(self, callback: Callable[[str], None]) -> None:
        """register a synchronous callback.

        callbacks must not block: they run inline on the listener, and a slow
        one delays every other subscriber.
        """
        self._callbacks.append(callback)

    async def publish(self, message: str) -> None:
        self._dispatch(message)
        try:
            await self._publisher.publish(message)
        except Exception as e:  # noqa
            logger.error("failed to broadcast on %s: %s", self._channel, e)

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._publisher.connect()
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._consumer.close()
        await self._publisher.close()

    async def _listen(self) -> None:
        """subscribe and dispatch forever, reconnecting on failure.

        a dropped subscription has to become a resubscription: without this the
        replica goes silent for the rest of its life and nothing reports it.
        """
        backoff = _BACKOFF_START_SEC
        while True:
            try:
                await self._consumer.connect()
                async for message in self._consumer.listen():
                    backoff = _BACKOFF_START_SEC
                    self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa
                logger.error("listener on %s dropped: %s", self._channel, e)
            await self._consumer.close()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_SEC)

    def _dispatch(self, message: str) -> None:
        for callback in self._callbacks:
            try:
                callback(message)
            except Exception as e:  # noqa
                logger.error("callback on %s failed: %s", self._channel, e)
