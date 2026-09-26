from __future__ import annotations

from typing import Protocol
from typing import runtime_checkable


@runtime_checkable
class Component(Protocol):
    """something with a lifetime tied to the process.

    ProxyRuntime starts components in declaration order and stops them in
    reverse, so anything holding a connection, a task or a subscription should
    satisfy this rather than inventing its own pair of verbs.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
