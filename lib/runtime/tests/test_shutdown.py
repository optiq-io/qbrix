"""signal handling for graceful shutdown.

these assert the one thing that makes a service's stop() reachable at all: a
termination signal has to resolve an event the serve loops are waiting on,
rather than ending the process where it stands.
"""

import asyncio
import os
import signal

import pytest

from qbrixruntime.shutdown import SIGNALS
from qbrixruntime.shutdown import shutdown_signal


async def _raise(sig: signal.Signals) -> None:
    """send sig to this process and let the loop deliver it."""
    os.kill(os.getpid(), sig)
    for _ in range(100):
        await asyncio.sleep(0.01)


class TestShutdownSignal:
    @pytest.mark.parametrize("sig", SIGNALS)
    async def test_signal_sets_the_event(self, sig):
        async with shutdown_signal() as event:
            assert not event.is_set()

            await asyncio.wait_for(asyncio.gather(_raise(sig), event.wait()), timeout=2)

            assert event.is_set()

    async def test_repeat_signal_is_idempotent(self):
        """a second ctrl-c must not escalate into an unhandled KeyboardInterrupt
        while teardown is still running."""
        async with shutdown_signal() as event:
            await asyncio.wait_for(
                asyncio.gather(_raise(signal.SIGINT), event.wait()), timeout=2
            )
            await _raise(signal.SIGINT)

            assert event.is_set()

    async def test_handlers_are_removed_on_exit(self):
        """the loop outlives the context in tests; a leaked handler would fire
        against an event nobody is waiting on."""
        loop = asyncio.get_running_loop()

        async with shutdown_signal():
            pass

        for sig in SIGNALS:
            assert loop.remove_signal_handler(sig) is False

    async def test_event_is_not_set_without_a_signal(self):
        async with shutdown_signal() as event:
            await asyncio.sleep(0.05)

            assert not event.is_set()
