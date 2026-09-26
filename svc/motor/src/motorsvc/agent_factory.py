import asyncio

from qbrixlog import get_logger
from qbrixcore.pool import Pool, Arm
from qbrixcore.agent import Agent
from qbrixcore.policy import BasePolicy

from motorsvc.cache import MotorCache
from motorsvc.param_backend import RedisBackedInMemoryParamBackend

logger = get_logger(__name__)


def _build_policy_map() -> dict[str, type[BasePolicy]]:
    registry = {}

    def collect(cls):
        for subclass in cls.__subclasses__():
            if hasattr(subclass, "name") and subclass.name:
                registry[subclass.name] = subclass
            collect(subclass)

    collect(BasePolicy)
    return registry


PROTOCOL_MAP = _build_policy_map()


class AgentFactory:
    def __init__(
        self, cache: MotorCache, param_backend: RedisBackedInMemoryParamBackend
    ):
        self._cache = cache
        self._param_backend = param_backend

    @staticmethod
    def _build_pool(pool_data: dict) -> Pool:
        pool = Pool(name=pool_data["name"], id=pool_data["id"])
        for arm_data in pool_data["arms"]:
            arm = Arm(
                name=arm_data["name"],
                id=arm_data["id"],
                is_active=arm_data.get("is_active", True),
            )
            pool.add_arm(arm)
        return pool

    async def get_or_create(self, tenant_id: str, experiment_record: dict) -> Agent:
        """
        Get cached agent or create new one.

        note: this method has an intentional race window between cache check
        and cache set. concurrent requests may build duplicate agents. this is
        acceptable because agents are stateless and param state lives in redis.
        """
        experiment_id = experiment_record["id"]

        # attention:
        #  ===== param update logic (stale-while-revalidate) ===== #
        #  1. check if params are in the TTL cache. if yes, use them directly.
        #    if not, there are two possible reasons:
        #     1a. param TTL expired — params were cached before but the 60s TTL lapsed
        #     1b. new agent / experiment — no params have ever been loaded
        #  2. distinguish 1a from 1b by checking the stale params store (plain dict, no TTL):
        #     2a. stale params exist (case 1a): serve them immediately so the select call
        #         never blocks, then kick off a background task to refresh from redis.
        #         the next request after the task completes will pick up fresh params.
        #     2b. no stale params (case 1b): first-ever load for this experiment on this
        #         instance, so we must fetch from redis synchronously. if redis has no
        #         params either (new experiment), initialize from the policy defaults.

        agent = self._cache.get_agent(tenant_id, experiment_id)
        if agent is not None:
            if self._param_backend.get(tenant_id, experiment_id) is None:
                stale = self._cache.get_stale_params(tenant_id, experiment_id)
                if stale is not None:
                    self._param_backend.set(tenant_id, experiment_id, stale)
                    asyncio.create_task(
                        self._refresh_params(tenant_id, experiment_id, agent.policy)
                    )
                else:
                    # unreachable | defensive fallback — should not happen in practice since
                    # set_params always populates stale params alongside the TTL cache.
                    # kept as a safety net for cold-start edge cases.
                    params = await self._param_backend.update_params(
                        tenant_id, experiment_id, agent.policy
                    )
                    if params is None:
                        params = agent.policy.build_state(
                            num_arms=len(agent.pool), **agent.params
                        )
                        self._param_backend.set(tenant_id, experiment_id, params)
            return agent

        # attention:
        #  if there is no agent, it's either because:
        #  1. it's the first request for an experiment
        #  2. there is a new replica / or instance restarted
        #  3. agent cache is expired / invalidated
        #  <->
        #  in all cases we need to regenerate the agent, meaning we need to fetch the policy, pool, etc.
        #  if it is not the first request, we already must have parameters, so we will fetch the
        #  parameters from the cache or redis.

        policy_name = experiment_record["policy"]
        policy_cls = PROTOCOL_MAP.get(policy_name)
        if policy_cls is None:
            raise ValueError(
                f"Unknown policy: {policy_name}. Available: {list(PROTOCOL_MAP.keys())}"
            )

        if self._param_backend.get(tenant_id, experiment_id) is None:
            params = await self._param_backend.update_params(
                tenant_id, experiment_id, policy_cls
            )
            if params is None:
                policy_params = experiment_record.get("policy_params", {})
                if policy_cls.name == "MetaBanditPolicy":
                    # meta-bandit: num_arms = number of learners, not pool arms
                    params = policy_cls.build_state(**policy_params)
                else:
                    params = policy_cls.build_state(
                        num_arms=len(experiment_record["pool"]["arms"]),
                        **policy_params,
                    )
                self._param_backend.set(tenant_id, experiment_id, params)

        pool = self._build_pool(experiment_record["pool"])
        scoped_param_backend = self._param_backend.scoped(tenant_id)
        agent = Agent(
            experiment_id=experiment_id,
            pool=pool,
            policy=policy_cls,
            params=experiment_record.get("policy_params", {}),
            param_backend=scoped_param_backend,
        )

        self._cache.set_agent(tenant_id, experiment_id, agent)
        return agent

    async def _refresh_params(
        self, tenant_id: str, experiment_id: str, policy: type[BasePolicy]
    ) -> None:
        """background refresh of params from redis (stale-while-revalidate)."""
        try:
            await self._param_backend.update_params(tenant_id, experiment_id, policy)
        except Exception as e:
            logger.error("background param refresh failed: %s", e)
