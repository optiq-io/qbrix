from __future__ import annotations

import redis.asyncio as redis

from qbrixstore.config import RedisSettings
from qbrixstore.event import Event
from qbrixstore.stream.topology import StreamSpec


class RedisStreamPublisher:
    def __init__(self, spec: StreamSpec, settings: RedisSettings | None = None):
        self._spec = spec
        self._settings = settings if settings is not None else RedisSettings()
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._settings.url, decode_responses=True)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def publish(self, event: Event) -> str:
        if self._client is None:
            raise RuntimeError("publisher not connected. call connect() first.")
        if not isinstance(event, self._spec.event):
            raise TypeError(
                f"{self._spec.name} carries {self._spec.event.__name__}, "
                f"got {type(event).__name__}"
            )
        return await self._client.xadd(
            self._spec.name,
            event.to_dict(),
            maxlen=self._spec.max_len,
            approximate=True,
        )


class RedisStreamConsumer:
    """one consumer of one group on one stream.

    the stream and group are required and checked against the registry, so a
    misrouted consumer fails at construction rather than silently reading the
    wrong stream. whether an ack may delete and where a new group starts are
    read from the spec rather than passed in, because those are properties of
    the stream that every one of its consumers has to agree on.

    reads return entries exactly as redis stores them — flat string maps. this
    is transport only: decoding them into events is StreamWorker's job, because
    a decode failure is a *policy* question (retry forever, or quarantine the
    entry and keep going) and only the loop that owns the batch can answer it.
    decoding here would mean one bad entry raising for the whole read.

    connect() only builds the client; the group is created by ensure_group(),
    which the worker drives.
    """

    def __init__(
        self,
        spec: StreamSpec,
        group: str,
        *,
        settings: RedisSettings | None = None,
        consumer_name: str = "worker-0",
    ):
        spec.require_group(group)
        self._spec = spec
        self._group = group
        self._settings = settings if settings is not None else RedisSettings()
        self._consumer_name = consumer_name
        self._client: redis.Redis | None = None

    @property
    def spec(self) -> StreamSpec:
        return self._spec

    @property
    def group(self) -> str:
        return self._group

    @property
    def consumer_name(self) -> str:
        return self._consumer_name

    @property
    def delete_on_ack(self) -> bool:
        return self._spec.delete_on_ack

    async def connect(self) -> None:
        self._client = redis.from_url(self._settings.url, decode_responses=True)

    async def ensure_group(self) -> None:
        """create the group if it does not exist.

        kept out of connect() because it is the first call that needs redis to
        be up; StreamWorker retries it, so a service can start before redis does.
        """
        if self._client is None:
            raise RuntimeError("consumer not connected. call connect() first.")
        try:
            await self._client.xgroup_create(
                self._spec.name,
                self._group,
                id=self._spec.start_id(self._group),
                mkstream=True,
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def consume(
        self, batch_size: int = 100, block_ms: int = 5000
    ) -> list[tuple[str, dict]]:
        """read undelivered entries for this group."""
        if self._client is None:
            raise RuntimeError("consumer not connected. call connect() first.")

        results = await self._client.xreadgroup(
            groupname=self._group,
            consumername=self._consumer_name,
            streams={self._spec.name: ">"},
            count=batch_size,
            block=block_ms,
        )

        return [entry for _, messages in results for entry in messages]

    async def ack(self, message_ids: list[str]) -> None:
        if self._client is None:
            raise RuntimeError("consumer not connected. call connect() first.")
        if message_ids:
            await self._client.xack(self._spec.name, self._group, *message_ids)
            if self._spec.delete_on_ack:
                await self._client.xdel(self._spec.name, *message_ids)

    async def claim_pending(
        self, count: int = 100, min_idle_ms: int = 0, start_id: str = "0-0"
    ) -> tuple[str, list[tuple[str, dict]]]:
        """claim entries this group read but never acked, e.g. after a crash.

        returns the cursor to pass as ``start_id`` on the next call, alongside
        the entries. redis reports ``"0-0"`` once the scan is complete.

        advancing that cursor is what makes a recovery sweep terminate. a
        consumer whose handler defers the ack — cortex until training, meter
        until stripe accepts — leaves the entries it just claimed in the PEL, so
        rescanning from the start would hand back the same ones forever.
        """
        if self._client is None:
            raise RuntimeError("consumer not connected. call connect() first.")

        results = await self._client.xautoclaim(
            self._spec.name,
            self._group,
            self._consumer_name,
            min_idle_time=min_idle_ms,
            start_id=start_id,
            count=count,
        )

        # [next_start_id, [(id, data), ...], [deleted_ids]] — the third element
        # is redis >= 7.0, which drops ids whose entry has been XDEL'd from the
        # PEL for us. that matters on qbrix:feedback, where cortex deletes on ack
        # and trace can hold pending ids for entries that no longer exist.
        if not results:
            return "0-0", []
        if len(results) < 2:
            return results[0], []

        return results[0], [(mid, data) for mid, data in results[1] if data]
