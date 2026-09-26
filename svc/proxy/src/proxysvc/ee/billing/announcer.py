from __future__ import annotations

from typing import Protocol


class TenantAnnouncer(Protocol):
    """the only thing billing needs from the invalidation bus.

    billing writes the tier; every other cache in the process — and in every
    other replica — derives from it. this is the seam between the two, narrow
    enough that billing never learns how the signal travels.
    """

    async def publish(self, tenant_id: str, /) -> None: ...


class NullTenantAnnouncer:
    """announces nowhere.

    billing evicts its own cache before announcing, so a process wired with
    this still answers correctly for itself; it just doesn't tell anyone else.
    """

    async def publish(self, tenant_id: str, /) -> None:
        return None
