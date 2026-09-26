from __future__ import annotations

import logging
import time

from qbrixstore.postgres.session import get_session
from qbrixstore.redis import RedisClient
from qbrixstore.event import AuditEvent

from proxysvc.config import ProxySettings
from proxysvc.core.error import GateExistsError
from proxysvc.core.events import EventEmitter
from proxysvc.mod.gate.cache import GateConfigCache
from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.controller import FeatureGate
from proxysvc.mod.gate.controller import GateDecision
from proxysvc.mod.gate.model.base import BaseArmModel
from proxysvc.mod.gate.repository import FeatureGateRepository
from proxysvc.mod.gate.schema import GateConfigPatchRequest
from proxysvc.mod.gate.schema import GateConfigRequest

logger = logging.getLogger(__name__)


class GateService:
    """feature gate service for experiment targeting.

    provides fast gate evaluation on the hot path with two-level caching and
    safe fallbacks, plus the persistent gate-config crud that keeps postgres
    and the cache in sync and emits audit events.
    """

    def __init__(
        self,
        redis: RedisClient,
        settings: ProxySettings,
        events: EventEmitter | None = None,
    ):
        self._cache = GateConfigCache(redis, settings)
        self._redis = redis
        self._settings = settings
        self._events = events

    async def evaluate(
        self,
        tenant_id: str,
        experiment_id: str,
        context_id: str,
        context_metadata: dict,
    ) -> BaseArmModel | None:
        """evaluate feature gate for a select request.

        returns:
            BaseArmModel: if gate determines a committed arm (skip bandit)
            None: if bandit selection should proceed

        safety: returns None on any error (fail-open to bandit path)
        """
        try:
            config = await self.get_config(tenant_id, experiment_id)
            if config is None:
                return None

            return FeatureGate.control(config, context_id, context_metadata)

        except Exception as e:
            logger.warning(
                f"gate evaluation failed for {experiment_id}, falling back to bandit: {e}"
            )
            return None

    async def evaluate_trace(
        self, tenant_id: str, experiment_id: str, context_id: str, metadata: dict
    ) -> tuple[FeatureGateConfig, GateDecision] | None:
        """dry-run the gate for a sample context.

        unlike `evaluate()` this does not fail open — a preview that silently
        reported "bandit proceeds" on an internal error would be a lie about
        what live traffic does. errors surface to the caller.
        """
        config = await self.get_config(tenant_id, experiment_id)
        if config is None:
            return None

        return config, FeatureGate.decide(config, context_id, metadata, trace=True)

    async def get_config(
        self, tenant_id: str, experiment_id: str
    ) -> FeatureGateConfig | None:
        """get gate config, reading through the cache to postgres on a miss.

        both cache levels expire (l1 `gate_cache_ttl`, l2 `gate_redis_ttl`) and
        nothing rewrites them outside a gate write, so without this a gate simply
        stopped existing minutes after it was saved: `evaluate()` fell back to the
        bandit for a committed experiment, and the console's GET 404'd, which made
        it POST a gate that postgres already held — the unique constraint on
        `experiment_id` then surfaced as "gate config creation failed".
        """
        config = await self._cache.get(tenant_id, experiment_id)
        if config is not None:
            return config
        if self._cache.known_absent(tenant_id, experiment_id):
            return None

        async with get_session() as session:
            repo = FeatureGateRepository(session, tenant_id)
            gate = await repo.get(experiment_id)
            config = repo.to_config(gate) if gate is not None else None

        if config is None:
            self._cache.mark_absent(tenant_id, experiment_id)
            return None

        await self._cache.set(tenant_id, experiment_id, config)
        return config

    async def set_config(
        self, tenant_id: str, experiment_id: str, config: FeatureGateConfig
    ) -> None:
        """set gate config in cache."""
        await self._cache.set(tenant_id, experiment_id, config)

    async def delete_config(self, tenant_id: str, experiment_id: str) -> None:
        """delete gate config from cache."""
        await self._cache.delete(tenant_id, experiment_id)

    def invalidate(self, tenant_id: str, experiment_id: str) -> None:
        """invalidate l1 cache entry."""
        self._cache.invalidate(tenant_id, experiment_id)

    # persistent gate-config crud

    async def create_gate_config(
        self,
        tenant_id: str,
        experiment_id: str,
        config: GateConfigRequest,
        actor_id: str = "",
    ) -> FeatureGateConfig | None:
        """create feature gate config for an experiment."""
        async with get_session() as session:
            repo = FeatureGateRepository(session, tenant_id)
            if not await repo.owns_experiment(experiment_id):
                return None
            if await repo.exists(experiment_id):
                raise GateExistsError(f"experiment already has a gate: {experiment_id}")
            await repo.create(experiment_id, config)
            gate = await repo.get(experiment_id)
            gate_config = repo.to_config(gate)
        # sync to redis after postgres commit succeeds
        await self.set_config(tenant_id, experiment_id, gate_config)
        self._events.emit_audit(
            AuditEvent(
                name="gate.created",
                tenant_id=tenant_id,
                actor_id=actor_id,
                resource_type="gate",
                resource_id=experiment_id,
                payload={},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return gate_config

    async def update_gate_config(
        self,
        tenant_id: str,
        experiment_id: str,
        config: GateConfigRequest,
        actor_id: str = "",
    ) -> FeatureGateConfig | None:
        """update feature gate config for an experiment."""
        async with get_session() as session:
            repo = FeatureGateRepository(session, tenant_id)
            updated = await repo.update(experiment_id, config)
            if updated is None:
                return None
            gate = await repo.get(experiment_id)
            gate_config = repo.to_config(gate)
        # sync to redis after postgres commit succeeds
        self.invalidate(tenant_id, experiment_id)
        await self.set_config(tenant_id, experiment_id, gate_config)
        self._events.emit_audit(
            AuditEvent(
                name="gate.updated",
                tenant_id=tenant_id,
                actor_id=actor_id,
                resource_type="gate",
                resource_id=experiment_id,
                payload={},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return gate_config

    async def patch_gate_config(
        self,
        tenant_id: str,
        experiment_id: str,
        patch: GateConfigPatchRequest,
        actor_id: str = "",
    ) -> FeatureGateConfig | None:
        """apply a partial update to an experiment's feature gate config."""
        changes = patch.changes()
        async with get_session() as session:
            repo = FeatureGateRepository(session, tenant_id)
            patched = await repo.patch(experiment_id, changes)
            if patched is None:
                return None
            gate = await repo.get(experiment_id)
            gate_config = repo.to_config(gate)
        # sync to redis after postgres commit succeeds
        self.invalidate(tenant_id, experiment_id)
        await self.set_config(tenant_id, experiment_id, gate_config)
        self._events.emit_audit(
            AuditEvent(
                name="gate.updated",
                tenant_id=tenant_id,
                actor_id=actor_id,
                resource_type="gate",
                resource_id=experiment_id,
                payload={"fields": sorted(changes)},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return gate_config

    async def delete_gate_config(
        self, tenant_id: str, experiment_id: str, actor_id: str = ""
    ) -> bool:
        """delete feature gate config for an experiment."""
        async with get_session() as session:
            repo = FeatureGateRepository(session, tenant_id)
            deleted = await repo.delete(experiment_id)
        if deleted:
            await self.delete_config(tenant_id, experiment_id)
            self._events.emit_audit(
                AuditEvent(
                    name="gate.deleted",
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    resource_type="gate",
                    resource_id=experiment_id,
                    payload={},
                    timestamp_ms=int(time.time() * 1000),
                )
            )
        return deleted
