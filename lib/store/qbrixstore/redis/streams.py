from __future__ import annotations

import redis.asyncio as redis
from redis.asyncio.client import Pipeline

from qbrixstore.config import RedisSettings
from qbrixstore.event import Event
from qbrixstore.stream.topology import StreamSpec


def _parse_id(entry_id: str) -> tuple[int, int]:
    ms, _, seq = entry_id.partition("-")
    return int(ms), int(seq or 0)


async def _consumer_groups(client: redis.Redis, spec: StreamSpec) -> list[dict]:
    try:
        return await client.xinfo_groups(spec.name)
    except redis.ResponseError as e:
        if "no such key" in str(e).lower():
            return []
        raise


async def consumer_group_backlog(
    client: redis.Redis, spec: StreamSpec, group: str
) -> int:
    """entries this group has not acked yet: undelivered plus pending.

    redis reports a group's lag as null once it can no longer count it, e.g.
    after the cap trimmed past the group; the stream's length bounds it then. a
    group that does not exist yet is owed whatever its start id will drain.
    """
    for info in await _consumer_groups(client, spec):
        if info["name"] == group:
            if info.get("lag") is None:
                return int(await client.xlen(spec.name))
            return int(info["lag"]) + int(info["pending"])
    if spec.start_id(group) == "$":
        return 0
    return int(await client.xlen(spec.name))


def stream_ms(entry_id: str) -> int:
    """the redis server time, in ms, at which the entry was added."""
    return _parse_id(entry_id)[0]


async def oldest_unfinished(
    client: redis.Redis, spec: StreamSpec, group: str
) -> str | None:
    """the oldest entry this group has not acked: its oldest pending one or
    the first it has not been delivered yet. none when it has finished every
    entry the stream holds.

    a group that does not exist yet has finished nothing.
    """
    last_delivered = "0-0"
    pending_min = None
    for info in await _consumer_groups(client, spec):
        if info["name"] == group:
            last_delivered = info["last-delivered-id"]
            if info["pending"]:
                summary = await client.xpending(spec.name, group)
                pending_min = summary["min"]
            break

    ms, seq = _parse_id(last_delivered)
    undelivered = await client.xrange(spec.name, min=f"{ms}-{seq + 1}", count=1)
    candidates = [entry_id for entry_id in (pending_min,) if entry_id]
    candidates += [entry_id for entry_id, _ in undelivered]
    return min(candidates, key=_parse_id, default=None)


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
            async with self._client.pipeline(transaction=True) as pipe:
                self.stage_ack(pipe, message_ids)
                await pipe.execute()

    @property
    def _quarantine_key(self) -> str:
        return f"qbrix:health:quarantined:{self._spec.name}:{self._group}"

    async def quarantine(self, message_ids: list[str]) -> None:
        """ack entries that cannot be decoded and add them to this group's
        install-wide total, in one transaction."""
        if self._client is None:
            raise RuntimeError("consumer not connected. call connect() first.")
        if message_ids:
            async with self._client.pipeline(transaction=True) as pipe:
                self.stage_ack(pipe, message_ids)
                # noinspection PyAsyncCall
                pipe.incrby(self._quarantine_key, len(message_ids))
                await pipe.execute()

    def stage_ack(self, pipe: Pipeline, message_ids: list[str]) -> None:
        """queue this group's ack onto a caller's transaction, so the ack lands
        with whatever else the caller writes, or not at all."""
        if not message_ids:
            return
        # noinspection PyAsyncCall
        pipe.xack(self._spec.name, self._group, *message_ids)
        if self._spec.delete_on_ack:
            # noinspection PyAsyncCall
            pipe.xdel(self._spec.name, *message_ids)

    async def backlog(self) -> int:
        if self._client is None:
            raise RuntimeError("consumer not connected. call connect() first.")
        return await consumer_group_backlog(self._client, self._spec, self._group)

    async def trim_acked(self) -> int:
        """trim the stream to the oldest entry any of its groups still needs.

        a group needs its oldest pending entry, or, with nothing pending,
        everything after its last delivered one. positions only move forward,
        so a group read before another advances can only make the trim smaller.
        only groups that exist protect entries: one that has never been created
        is not owed the history before it joins. returns the number trimmed.
        """
        if self._client is None:
            raise RuntimeError("consumer not connected. call connect() first.")

        floor: tuple[int, int] | None = None
        floor_id = "0-0"
        for info in await _consumer_groups(self._client, self._spec):
            needed = info["last-delivered-id"]
            if info["pending"]:
                summary = await self._client.xpending(self._spec.name, info["name"])
                needed = summary["min"] or needed
            parsed = _parse_id(needed)
            if floor is None or parsed < floor:
                floor, floor_id = parsed, needed

        if floor is None or floor == (0, 0):
            return 0
        return await self._client.xtrim(
            self._spec.name, minid=floor_id, approximate=False
        )

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
        # is redis >= 7.0, which drops ids whose entry no longer exists from the
        # PEL for us. on a fanned-out stream that happens only when the cap has
        # trimmed past a group that lagged by more than max_len.
        if not results:
            return "0-0", []
        if len(results) < 2:
            return results[0], []

        return results[0], [(mid, data) for mid, data in results[1] if data]
