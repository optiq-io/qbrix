from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis

from proxysvc.transport.mcp.error import running

REPEAT_WINDOW_SEC = 300

_PENDING = "pending"
_POLL_SEC = 0.1
_WAIT_SEC = 5.0


def repeat_key(connection_id: str, tool: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        [connection_id, tool, arguments], sort_keys=True, separators=(",", ":")
    )
    return f"qbrix:mcp:repeat:{hashlib.sha256(canonical.encode()).hexdigest()}"


class RepeatGuard:
    """runs a change once per connection, tool and arguments within the window.

    agents retry, and so do networks and multi round-trip requests; a repeat
    returns the first call's result instead of changing anything twice. a call
    that fails leaves nothing behind, so a corrected retry runs.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        window_sec: int = REPEAT_WINDOW_SEC,
        wait_sec: float = _WAIT_SEC,
    ):
        self._redis = redis
        self._window_sec = window_sec
        self._wait_sec = wait_sec

    async def once(
        self,
        key: str,
        call: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        if await self._redis.set(key, _PENDING, nx=True, ex=self._window_sec):
            try:
                result = await call()
            except BaseException:
                await self._redis.delete(key)
                raise
            await self._redis.set(key, json.dumps(result), xx=True, keepttl=True)
            return result
        return await self._first(key, call)

    async def _first(
        self, key: str, call: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        waited = 0.0
        while True:
            stored = await self._redis.get(key)
            if stored is None:
                return await self.once(key, call)
            if stored != _PENDING:
                return json.loads(stored)
            if waited >= self._wait_sec:
                raise running()
            await asyncio.sleep(_POLL_SEC)
            waited += _POLL_SEC
