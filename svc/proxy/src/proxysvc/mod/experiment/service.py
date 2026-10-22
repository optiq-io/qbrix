from __future__ import annotations

import asyncio
import time

from qbrixlog import get_logger
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import Learning
from qbrixstore.redis.client import RedisClient
from qbrixstore.event import AuditEvent

from proxysvc.config import ProxySettings
from proxysvc.core.actor import Actor
from proxysvc.core.entitlements import Entitlements
from proxysvc.core.events import EventEmitter
from proxysvc.core.error import BadPolicyParamsError
from proxysvc.core.error import ExperimentLimitError
from proxysvc.core.error import ExperimentRunningError
from proxysvc.core.error import LearnerExperimentDeleteError
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.serialize import learning_snapshot
from proxysvc.mod.change.serialize import snapshot
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.experiment.cache import ExperimentState
from proxysvc.mod.experiment.cache import ExperimentStateCache
from proxysvc.mod.experiment.repository import ExperimentRepository
from proxysvc.mod.experiment.serialize import experiment_to_dict
from proxysvc.mod.gate import GateService
from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.repository import FeatureGateRepository
from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.mod.pool.repository import PoolRepository
from proxysvc.mod.pool.serialize import pool_to_dict
from proxysvc.transport.grpc.client import CortexClient
from proxysvc.util import _assert_context_dim_unchanged
from proxysvc.util import _assert_context_schema_unchanged
from proxysvc.util import _inspect_params
from proxysvc.util import _resolve_context_schema

logger = get_logger(__name__)


class ExperimentService:
    """experiment lifecycle: crud, meta-bandit composition, plan-limit
    enforcement, gate-config loading, and redis sync for motorsvc.

    owns the experiment-state cache (pause + pool) read by the agent hot path;
    crud here invalidates it on update/pause/delete, mirroring how GateService
    owns the gate-config cache.
    """

    def __init__(
        self,
        *,
        redis: RedisClient,
        gate_service: GateService,
        cortex_client: CortexClient,
        events: EventEmitter,
        settings: ProxySettings,
        entitlements: Entitlements,
    ):
        self._redis = redis
        self._entitlements = entitlements
        self._gate_service = gate_service
        self._cortex_client = cortex_client
        self._events = events
        self._cache = ExperimentStateCache(redis, settings)

    async def get_state(
        self, tenant_id: str, experiment_id: str
    ) -> ExperimentState | None:
        """read experiment pause-state + pool from the cache (l1 -> l2).

        serves the agent select hot path; returns None when no record exists.
        """
        return await self._cache.get(tenant_id, experiment_id)

    async def list_pool_experiments(self, tenant_id: str, pool_id: str) -> list[dict]:
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)
            experiments = await repo.list_by_pool(pool_id)
            return [experiment_to_dict(exp) for exp in experiments]

    async def _check_plan_limit(
        self,
        repo: ExperimentRepository,
        plan_tier: str,
        enabled: bool,
    ) -> None:
        max_experiments = self._entitlements.limits(plan_tier)["max_active_experiments"]
        if max_experiments != -1 and enabled:
            active_count = await repo.count_active()
            if active_count >= max_experiments:
                raise ExperimentLimitError(
                    f"active experiment limit reached for {plan_tier} plan ({max_experiments} experiments)"
                )

    @staticmethod
    async def _load_gate_config(
        session,
        tenant_id: str,
        experiment_id: str,
        feature_gate_config: GateConfigRequest | None,
    ) -> FeatureGateConfig | None:
        if not feature_gate_config:
            return None
        gate_repo = FeatureGateRepository(session, tenant_id)
        gate = await gate_repo.get(experiment_id)
        if gate:
            return gate_repo.to_config(gate)
        return None

    async def create_experiment(
        self,
        tenant_id: str,
        name: str,
        pool_id: str,
        policy: str = "",
        policy_params: dict | None = None,
        enabled: bool = True,
        feature_gate_config: GateConfigRequest | None = None,
        *,
        actor: Actor,
        plan_tier: str = "free",
    ) -> dict:
        policy_params = _resolve_context_schema(policy_params)
        _inspect_params(policy, policy_params)

        gate_config = None
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)
            await self._check_plan_limit(repo, plan_tier, enabled)

            experiment = await repo.create(
                name=name,
                pool_id=pool_id,
                policy=policy,
                policy_params=policy_params or {},
                enabled=enabled,
                feature_gate_config=feature_gate_config,
            )
            experiment_id = experiment.id

            # reload with eager-loaded relationships (pool, feature_gate)
            # to avoid lazy-load greenlet errors in async context
            experiment = await repo.get(experiment_id)
            exp_dict = experiment_to_dict(experiment)
            gate_config = await self._load_gate_config(
                session, tenant_id, experiment_id, feature_gate_config
            )
            await ChangeRepository(session, tenant_id).record(
                "experiment.create",
                "experiment",
                experiment_id,
                actor,
                after=snapshot(exp_dict),
            )

        # sync to redis after postgres commit succeeds
        if gate_config:
            await self._gate_service.set_config(tenant_id, experiment_id, gate_config)
        await self._sync_experiment_to_redis(tenant_id, experiment_id, pool_id)
        self._events.emit_audit(
            AuditEvent(
                name="experiment.created",
                tenant_id=tenant_id,
                actor_id=actor.user_id,
                resource_type="experiment",
                resource_id=experiment_id,
                payload={"name": name, "pool_id": pool_id, "policy": policy},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return exp_dict

    async def create_meta_experiment(
        self,
        tenant_id: str,
        name: str,
        pool_id: str,
        policy_params: dict,
        enabled: bool = True,
        feature_gate_config: GateConfigRequest | None = None,
        *,
        actor: Actor,
        plan_tier: str = "free",
    ) -> dict:
        """create a meta-bandit experiment with automatic policy selection.

        creates a meta experiment with MetaBanditPolicy and M learner
        experiments. the learner portfolio is scoped to the reward type
        and context configuration provided in policy_params, so contextual
        bandits can participate when the caller passes dim.
        """
        from qbrixcore.policy._meta import build_learners  # noqa

        policy_params = _resolve_context_schema(policy_params)

        reward_type = policy_params.get("reward_type")
        context_schema = policy_params.get("context_schema")
        # a declared schema is itself the request for contextual learners
        use_context = bool(policy_params.get("use_context", False)) or (
            context_schema is not None
        )
        dim = policy_params.get("dim")

        try:
            learners = build_learners(
                reward_type=reward_type,
                use_context=use_context,
                dim=dim,
            )
        except ValueError as e:
            raise BadPolicyParamsError(str(e)) from e

        meta_params: dict = {"learners": []}
        if reward_type is not None:
            meta_params["reward_type"] = reward_type
        if use_context:
            meta_params["use_context"] = True
            meta_params["dim"] = dim
            # the select edge encodes against the parent, so the schema is
            # carried here; learners only ever need the derived dim
            if context_schema is not None:
                meta_params["context_schema"] = context_schema

        gate_config = None
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)

            # plan limits count only parent experiments
            await self._check_plan_limit(repo, plan_tier, enabled)

            parent = await repo.create(
                name=name,
                pool_id=pool_id,
                policy="MetaBanditPolicy",
                policy_params=meta_params,
                enabled=enabled,
                feature_gate_config=feature_gate_config,
            )
            meta_id = parent.id

            learner_ids: list[str] = []
            for i, learner in enumerate(learners):
                learner_exp = await repo.create(
                    name=f"{name}__learner_{i}_{learner['policy']}",
                    pool_id=pool_id,
                    policy=learner["policy"],
                    policy_params=learner.get("policy_params", {}),
                    enabled=True,
                    meta_experiment_id=meta_id,
                )
                learner_ids.append(learner_exp.id)

            # build a fresh dict for the update — policy_params is a plain JSON
            # column (not MutableDict), so sqlalchemy won't detect in-place
            # mutation of the original meta_params reference shared with create().
            meta_params = {**meta_params, "learners": learner_ids}
            await repo.update(meta_id, policy_params=meta_params)

            parent = await repo.get(meta_id)
            exp_dict = experiment_to_dict(parent)
            gate_config = await self._load_gate_config(
                session, tenant_id, meta_id, feature_gate_config
            )
            await ChangeRepository(session, tenant_id).record(
                "experiment.create",
                "experiment",
                meta_id,
                actor,
                after=await self._snapshot(repo, parent),
            )

        # sync learners first so motor can resolve them before the meta
        # parent starts routing selections at the meta level
        for learner_id in learner_ids:
            await self._sync_experiment_to_redis(tenant_id, learner_id, pool_id)
        await self._sync_experiment_to_redis(tenant_id, meta_id, pool_id)

        if gate_config:
            await self._gate_service.set_config(tenant_id, meta_id, gate_config)

        self._events.emit_audit(
            AuditEvent(
                name="experiment.created",
                tenant_id=tenant_id,
                actor_id=actor.user_id,
                resource_type="experiment",
                resource_id=meta_id,
                payload={
                    "name": name,
                    "pool_id": pool_id,
                    "policy": "MetaBanditPolicy",
                    "mode": "auto",
                    "reward_type": reward_type,
                    "use_context": use_context,
                    "dim": dim,
                    "learners": learner_ids,
                },
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return exp_dict

    async def get_experiment(self, tenant_id: str, experiment_id: str) -> dict | None:
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)
            experiment = await repo.get(experiment_id)
            if experiment is None:
                return None
            return experiment_to_dict(experiment)

    async def list_experiments(
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
        enabled: bool | None = None,
    ) -> list[dict]:
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)
            experiments = await repo.list(
                limit=limit,
                offset=offset,
                search=search,
                enabled=enabled,
            )
            return [experiment_to_dict(exp) for exp in experiments]

    async def update_experiment(
        self,
        tenant_id: str,
        experiment_id: str,
        *,
        actor: Actor,
        plan_tier: str = "free",
        **kwargs,
    ) -> dict | None:
        return await self._update(
            tenant_id, experiment_id, kwargs, actor=actor, plan_tier=plan_tier
        )

    async def restore_experiment(
        self,
        tenant_id: str,
        experiment_id: str,
        fields: dict,
        *,
        actor: Actor,
        undoing: Undoing,
        plan_tier: str = "free",
    ) -> dict | None:
        """write back fields an earlier change recorded, as an update."""
        return await self._update(
            tenant_id,
            experiment_id,
            fields,
            actor=actor,
            plan_tier=plan_tier,
            undoing=undoing,
        )

    async def _update(
        self,
        tenant_id: str,
        experiment_id: str,
        kwargs: dict,
        *,
        actor: Actor,
        plan_tier: str,
        undoing: Undoing | None = None,
    ) -> dict | None:
        """an undo assigns stored values as they are: they were valid when
        recorded, and a stored context schema already carries the derived dim
        that _resolve_context_schema rejects."""
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)
            current = await repo.get(experiment_id)
            if current is None:
                return None

            if kwargs.get("enabled"):
                max_experiments = self._entitlements.limits(plan_tier)[
                    "max_active_experiments"
                ]
                if max_experiments != -1:
                    active_count = await repo.count_active()
                    if active_count >= max_experiments:
                        raise ExperimentLimitError(
                            f"active experiment limit reached for {plan_tier} plan with {max_experiments} experiments)"
                        )

            if "policy_params" in kwargs and undoing is None:
                # patch replaces policy_params wholesale (see ExperimentRepository.update);
                # validate against the experiment's current policy.
                params = _resolve_context_schema(kwargs["policy_params"])
                _assert_context_schema_unchanged(current.policy_params, params)
                _assert_context_dim_unchanged(current.policy_params, params)
                kwargs["policy_params"] = params
                _inspect_params(current.policy, params)

            # serialized before update, which mutates the same identity-mapped row
            before = await self._snapshot(repo, current)
            learning = await self._learning(tenant_id, current)
            if undoing is None:
                experiment = await repo.update(experiment_id, **kwargs)
            else:
                experiment = await repo.restore(experiment_id, kwargs)
            exp_dict = experiment_to_dict(experiment)
            pool_id = experiment.pool_id
            await ChangeRepository(session, tenant_id).record(
                "experiment.update",
                "experiment",
                experiment_id,
                actor,
                before=before,
                after=await self._snapshot(repo, experiment),
                learning=learning,
                undoing=undoing,
            )
        await self._sync_experiment_to_redis(tenant_id, experiment_id, pool_id)
        self._cache.invalidate(tenant_id, experiment_id)
        self._events.emit_audit(
            AuditEvent(
                name="experiment.updated",
                tenant_id=tenant_id,
                actor_id=actor.user_id,
                resource_type="experiment",
                resource_id=experiment_id,
                payload={"changed_fields": list(kwargs.keys())},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return exp_dict

    async def delete_experiment(
        self, tenant_id: str, experiment_id: str, *, actor: Actor
    ) -> bool:
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)
            experiment = await repo.get(experiment_id)
            if experiment is None:
                return False
            if experiment.meta_experiment_id:
                raise LearnerExperimentDeleteError(
                    "cannot delete a learner experiment managed by a meta-bandit. "
                    "delete the meta experiment instead."
                )
            before = await self._snapshot(repo, experiment)
            learning = await self._learning(tenant_id, experiment)
            await repo.delete(experiment_id)
            await ChangeRepository(session, tenant_id).record(
                "experiment.delete",
                "experiment",
                experiment_id,
                actor,
                before=before,
                learning=learning,
            )
        await self._redis.delete_experiment(tenant_id, experiment_id)
        self._cache.invalidate(tenant_id, experiment_id)
        await self._gate_service.delete_config(tenant_id, experiment_id)
        self._events.emit_audit(
            AuditEvent(
                name="experiment.deleted",
                tenant_id=tenant_id,
                actor_id=actor.user_id,
                resource_type="experiment",
                resource_id=experiment_id,
                payload={},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return True

    async def reset_experiment(
        self, tenant_id: str, experiment_id: str, *, actor: Actor
    ) -> dict | None:
        """reset an experiment's learned params back to its configured policy_params.

        clearing the params and the learning record is sufficient: motorsvc and
        cortexsvc lazily re-initialize from the experiment's policy_params (which
        training never mutates), and cortex's write is fenced against the reset.
        requires the experiment to be paused to avoid an in-flight cortex write clobbering
        the reset.
        """
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)
            experiment = await repo.get(experiment_id)
            if experiment is None:
                return None
            if experiment.enabled:
                raise ExperimentRunningError(
                    "pause the experiment before resetting its parameters"
                )
            exp_dict = experiment_to_dict(experiment)
            state = await self._snapshot(repo, experiment)

        await self._flush_cortex(experiment_id, "reset")

        # after the flush, so the snapshot includes what was in flight; inside
        # the transaction, so a failed reset leaves no record of one
        async with get_session() as session:
            await ChangeRepository(session, tenant_id).record(
                "experiment.reset",
                "experiment",
                experiment_id,
                actor,
                before=state,
                after=state,
                learning=await self._learning(tenant_id, experiment),
            )
            await self._redis.reset_learning(tenant_id, experiment_id)
        self._events.emit_audit(
            AuditEvent(
                name="experiment.reset",
                tenant_id=tenant_id,
                actor_id=actor.user_id,
                resource_type="experiment",
                resource_id=experiment_id,
                payload={},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return exp_dict

    async def restore_learning(
        self,
        tenant_id: str,
        experiment_id: str,
        learning: Learning,
        *,
        baseline_applied: int,
        actor: Actor,
        undoing: Undoing,
    ) -> dict | None:
        """put back what an experiment had learned, exactly as recorded.

        outcomes learned since the undone change are dropped, not re-applied:
        their entries are already acked. the undo records how many as
        ``dropped``, counted above ``baseline_applied``, the applied count the
        undone change left behind.
        """
        async with get_session() as session:
            repo = ExperimentRepository(session, tenant_id)
            experiment = await repo.get(experiment_id)
            if experiment is None:
                return None
            if experiment.enabled:
                raise ExperimentRunningError(
                    "pause the experiment before restoring what it had learned"
                )
            exp_dict = experiment_to_dict(experiment)
            state = await self._snapshot(repo, experiment)

        await self._flush_cortex(experiment_id, "restore")

        async with get_session() as session:
            change = await ChangeRepository(session, tenant_id).record(
                "experiment.restore",
                "experiment",
                experiment_id,
                actor,
                before=state,
                after=state,
                undoing=undoing,
            )
            replaced = await self._redis.restore_learning(
                tenant_id, experiment_id, learning
            )
            change.learning = {
                experiment_id: {
                    **learning_snapshot({experiment_id: replaced})[experiment_id],
                    "dropped": replaced.applied - baseline_applied,
                }
            }
        self._events.emit_audit(
            AuditEvent(
                name="experiment.restored",
                tenant_id=tenant_id,
                actor_id=actor.user_id,
                resource_type="experiment",
                resource_id=experiment_id,
                payload={},
                timestamp_ms=int(time.time() * 1000),
            )
        )
        return exp_dict

    async def _flush_cortex(self, experiment_id: str, before: str) -> None:
        """best-effort drain of in-flight feedback, so this write is the last."""
        if self._cortex_client:
            try:
                await self._cortex_client.flush_batch(experiment_id)
            except Exception as e:  # noqa
                logger.warning("cortex flush before %s failed: %s", before, e)

    @staticmethod
    def _learner_ids(experiment) -> list[str]:
        if experiment.policy != "MetaBanditPolicy":
            return []
        return list((experiment.policy_params or {}).get("learners", []))

    async def _snapshot(self, repo: ExperimentRepository, experiment) -> dict:
        """the experiment as a change stores it; a meta experiment carries its
        learners, since they are created and deleted with it."""
        state = snapshot(experiment_to_dict(experiment))
        learner_ids = self._learner_ids(experiment)
        if learner_ids:
            learners = [await repo.get(lid) for lid in learner_ids]
            state["learners"] = [
                snapshot(experiment_to_dict(learner)) for learner in learners if learner
            ]
        return state

    async def _learning(self, tenant_id: str, experiment) -> dict:
        ids = [experiment.id, *self._learner_ids(experiment)]
        learnings = await asyncio.gather(
            *(self._redis.read_learning(tenant_id, eid) for eid in ids)
        )
        return learning_snapshot(dict(zip(ids, learnings)))

    async def _sync_experiment_to_redis(
        self, tenant_id: str, experiment_id: str, pool_id: str
    ) -> None:
        """sync experiment with full pool data to redis for motorsvc."""
        async with get_session() as session:
            pool_repo = PoolRepository(session, tenant_id)
            pool = await pool_repo.get(pool_id)
            experiment_repo = ExperimentRepository(session, tenant_id)
            experiment = await experiment_repo.get(experiment_id)

            redis_data = {
                "id": experiment.id,
                "tenant_id": tenant_id,
                "name": experiment.name,
                "pool_id": experiment.pool_id,
                "pool": pool_to_dict(pool),
                "policy": experiment.policy,
                "policy_params": experiment.policy_params,
                "enabled": experiment.enabled,
            }
            await self._redis.set_experiment(tenant_id, experiment_id, redis_data)
