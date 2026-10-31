from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from qbrixstore.postgres.session import get_session

from proxysvc.core.error import PinTargetNotFoundError
from proxysvc.mod.pin.repository import LOOP
from proxysvc.mod.pin.repository import METRIC
from proxysvc.mod.pin.repository import PinRepository

RETIRED = "retired"


class PinService:
    """a person's own pinned loops and metrics. a pin is navigation, not a
    change to what it points at, so nothing here records a change."""

    async def list(self, tenant_id: str, user_id: str) -> list[dict]:
        async with get_session() as session:
            repo = PinRepository(session)
            pins = await repo.list(tenant_id, user_id)
            loops = await repo.loops(tenant_id, _refs(pins, LOOP))
            metrics = await repo.metrics(tenant_id, _refs(pins, METRIC))

            listed = []
            for pin in pins:
                if pin.kind == LOOP:
                    loop = loops.get(pin.ref)
                    if loop is not None and loop.state != RETIRED:
                        listed.append(_row(pin, loop.name, loop.key, loop.state))
                else:
                    metric = metrics.get(pin.ref)
                    if metric is not None:
                        listed.append(_row(pin, metric.name, metric.name, None))
            return listed

    async def pin(self, tenant_id: str, user_id: str, kind: str, ref: str) -> None:
        try:
            async with get_session() as session:
                repo = PinRepository(session)
                if not await repo.target_exists(tenant_id, kind, ref):
                    raise PinTargetNotFoundError(f"no {kind} {ref} to pin")
                if await repo.get(user_id, kind, ref) is None:
                    await repo.create(tenant_id, user_id, kind, ref)
        except IntegrityError:
            # another request pinned it first, which is what this one asked for
            return

    async def unpin(self, user_id: str, kind: str, ref: str) -> None:
        async with get_session() as session:
            await PinRepository(session).delete(user_id, kind, ref)


def _refs(pins, kind: str) -> list[str]:
    return [pin.ref for pin in pins if pin.kind == kind]


def _row(pin, name: str, key: str, state: str | None) -> dict:
    return {
        "kind": pin.kind,
        "ref": pin.ref,
        "name": name,
        "key": key,
        "state": state,
    }
