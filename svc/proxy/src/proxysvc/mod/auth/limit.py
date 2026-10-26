from __future__ import annotations

import logging

from redis.asyncio import Redis
from redis.exceptions import OutOfMemoryError

logger = logging.getLogger(__name__)


async def count_this_minute(client: Redis, rate_key: str) -> int | None:
    """count one request in this minute's window and return the count before
    it, or None when redis is full.

    a full redis refuses the increment. the abuse guard then lets the
    request through rather than failing selection, which keeps serving
    from motor's cached parameters while learning is stalled.
    """
    pipe = client.pipeline()
    # noinspection PyAsyncCall
    pipe.get(rate_key)
    # noinspection PyAsyncCall
    pipe.incr(rate_key)
    # noinspection PyAsyncCall
    pipe.expire(rate_key, 120)
    try:
        response = await pipe.execute()
    except OutOfMemoryError as e:
        logger.error("redis is full, rate limit not applied: %s", e)
        return None
    return int(response[0]) if response[0] else 0
