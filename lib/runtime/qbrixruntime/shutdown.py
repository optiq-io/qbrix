from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import AsyncIterator

from qbrixlog import get_logger

logger = get_logger(__name__)

SIGNALS = (signal.SIGTERM, signal.SIGINT)


@contextlib.asynccontextmanager
async def shutdown_signal() -> AsyncIterator[asyncio.Event]:
    """yield an event that is set when the process is asked to terminate.

    kubernetes stops pods with SIGTERM, whose default disposition would end the
    process before any teardown runs. handling it here is what makes a service's
    ordered stop() reachable at all.

    install these before any library that manages its own signals. uvicorn,
    which proxy runs, swaps in its own handler in capture_signals(), restores
    whatever it displaced, then re-raises the signal — so with no handler of
    ours it restores SIG_DFL and the re-raise kills the process mid-teardown. it
    only survives today because a container's pid 1 is exempt from
    default-disposition signals; under tini, a shell wrapper or
    shareProcessNamespace it is not. leaving our handler as the one uvicorn
    restores makes the re-raise land here instead.

    handlers are removed on exit so nothing leaks into a later event loop.
    """
    loop = asyncio.get_running_loop()
    event = asyncio.Event()

    def trigger(sig: signal.Signals) -> None:
        if not event.is_set():
            logger.info("received %s, shutting down", sig.name)
        event.set()

    installed: list[signal.Signals] = []
    for sig in SIGNALS:
        try:
            loop.add_signal_handler(sig, trigger, sig)
        except NotImplementedError:
            logger.warning("signal %s not supported on this platform", sig.name)
            continue
        installed.append(sig)

    try:
        yield event
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)
