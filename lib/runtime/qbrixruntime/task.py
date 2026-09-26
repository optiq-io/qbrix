from __future__ import annotations

import asyncio
import contextlib


async def drain(*tasks: asyncio.Task) -> None:
    """cancel helper tasks and absorb their cancellation."""
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
