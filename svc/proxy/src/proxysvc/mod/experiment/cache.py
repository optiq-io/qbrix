from __future__ import annotations

from functools import cached_property

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from qbrixcore.context_schema import ContextSchema
from qbrixstore.redis import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.cache import TwoTierCache

_EXPERIMENT_NAMESPACE = "qbrix:tenant"


class ExperimentState(BaseModel):
    """slim view of the experiment record needed on the select hot path.

    validates the full record written by _sync_experiment_to_redis (extra
    fields ignored); only enabled + pool + policy_params are read here.
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    pool: dict = Field(default_factory=dict)
    policy_params: dict = Field(default_factory=dict)

    @property
    def context_dim(self) -> int | None:
        """the context width this experiment requires, or None if not contextual.

        set for every contextual shape: passed directly on manual creation,
        merged into each contextual learner by build_learners, and carried on
        the parent of a contextual meta experiment.
        """
        dim = self.policy_params.get("dim")
        return dim if isinstance(dim, int) and dim > 0 else None

    @cached_property
    def context_schema(self) -> ContextSchema | None:
        """the declared schema, or None for the dim-only escape hatch.

        cached because the select hot path reads it per request while this
        model is held in l1; the stored form is already canonical, written by
        _resolve_context_schema at create.
        """
        declared = self.policy_params.get("context_schema")
        if declared is None:
            return None
        return ContextSchema.model_validate(declared)


class ExperimentStateCache:
    """read-through l1 -> l2 cache for experiment pause state + pool.

    reads the same redis entry motorsvc reads (written via
    RedisClient.set_experiment); it never writes l2, so the full record is
    preserved. l1 freshness on a write replica comes from invalidate(); other
    replicas converge within the l1 ttl, mirroring the gate config cache.
    """

    def __init__(self, redis: RedisClient, settings: ProxySettings) -> None:
        self._tier: TwoTierCache[ExperimentState] = TwoTierCache(
            redis=redis.client,
            model=ExperimentState,
            namespace=_EXPERIMENT_NAMESPACE,
            l1_maxsize=settings.experiment_cache_maxsize,
            l1_ttl=settings.experiment_cache_ttl,
            l2_ttl=settings.experiment_cache_ttl,
        )

    async def get(self, tenant_id: str, experiment_id: str) -> ExperimentState | None:
        """get experiment state from cache hierarchy (l1 -> l2)."""
        return await self._tier.get(tenant_id, "experiment", experiment_id)

    def invalidate(self, tenant_id: str, experiment_id: str) -> None:
        """invalidate the local l1 entry (l2 is owned by set_experiment)."""
        self._tier.invalidate(tenant_id, "experiment", experiment_id)
