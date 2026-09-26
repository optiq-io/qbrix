from __future__ import annotations

import time

from qbrixstore.postgres.session import get_session
from qbrixstore.event import AuditEvent

from proxysvc.core.events import EventEmitter
from proxysvc.core.error import PoolHasExperimentsError
from proxysvc.mod.experiment.repository import ExperimentRepository
from proxysvc.mod.pool.repository import PoolRepository
from proxysvc.mod.pool.serialize import pool_to_dict


class PoolService:
    """pool crud with ee audit emission.

    the delete guard reads linked experiments through ExperimentRepository
    directly, so the pool domain never depends on the experiment service.
    """

    def __init__(self, events: EventEmitter):
        self._events = events

    async def create_pool(
        self, tenant_id: str, name: str, arms: list[dict], actor_id: str = ""
    ) -> dict:
        async with get_session() as session:
            repo = PoolRepository(session, tenant_id)
            pool = await repo.create(name, arms)
            pool_dict = pool_to_dict(pool)
        self._events.emit_audit(
            AuditEvent(
                name="pool.created",
                tenant_id=tenant_id,
                actor_id=actor_id,
                resource_type="pool",
                resource_id=pool_dict["id"],
                payload={"name": name, "arm_count": len(arms)},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return pool_dict

    async def get_pool(self, tenant_id: str, pool_id: str) -> dict | None:
        async with get_session() as session:
            repo = PoolRepository(session, tenant_id)
            pool = await repo.get(pool_id)
            if pool is None:
                return None
            return pool_to_dict(pool)

    async def list_pools(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        async with get_session() as session:
            repo = PoolRepository(session, tenant_id)
            pools = await repo.list(limit=limit, offset=offset)
            return [pool_to_dict(pool) for pool in pools]

    async def update_pool(
        self, tenant_id: str, pool_id: str, actor_id: str = "", **kwargs
    ) -> dict | None:
        async with get_session() as session:
            repo = PoolRepository(session, tenant_id)
            pool = await repo.update(pool_id, **kwargs)
            if pool is None:
                return None
            pool_dict = pool_to_dict(pool)
        self._events.emit_audit(
            AuditEvent(
                name="pool.updated",
                tenant_id=tenant_id,
                actor_id=actor_id,
                resource_type="pool",
                resource_id=pool_id,
                payload={"changed_fields": list(kwargs.keys())},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return pool_dict

    async def delete_pool(
        self, tenant_id: str, pool_id: str, actor_id: str = ""
    ) -> bool:
        async with get_session() as session:
            exp_repo = ExperimentRepository(session, tenant_id)
            linked = await exp_repo.list_by_pool(pool_id)
            if linked:
                names = ", ".join(exp.name for exp in linked[:5])
                suffix = f" and {len(linked) - 5} more" if len(linked) > 5 else ""
                raise PoolHasExperimentsError(
                    f"cannot delete pool: it is used by {len(linked)} experiment(s) "
                    f"({names}{suffix}). delete or reassign them first."
                )
            repo = PoolRepository(session, tenant_id)
            deleted = await repo.delete(pool_id)
        if deleted:
            self._events.emit_audit(
                AuditEvent(
                    name="pool.deleted",
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    resource_type="pool",
                    resource_id=pool_id,
                    payload={},
                    timestamp_ms=int(time.time() * 1000),
                )
            )
        return deleted
