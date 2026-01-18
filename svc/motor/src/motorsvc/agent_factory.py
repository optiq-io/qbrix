from qbrixcore.pool import Pool, Arm
from qbrixcore.agent import Agent
from qbrixcore.protoc import BaseProtocol

from motorsvc.cache import MotorCache
from motorsvc.param_backend import RedisParamBackend


def _build_protocol_map() -> dict[str, type[BaseProtocol]]:
    registry = {}
    def collect(cls):
        for subclass in cls.__subclasses__():
            if hasattr(subclass, "name") and subclass.name:
                registry[subclass.name] = subclass
            collect(subclass)
    collect(BaseProtocol)
    return registry


PROTOCOL_MAP = _build_protocol_map()


class AgentFactory:
    def __init__(self, cache: MotorCache, param_backend: RedisParamBackend):
        self._cache = cache
        self._param_backend = param_backend

    @staticmethod
    def _build_pool(pool_data: dict) -> Pool:
        pool = Pool(name=pool_data["name"], id=pool_data["id"])
        for arm_data in pool_data["arms"]:
            arm = Arm(
                name=arm_data["name"],
                id=arm_data["id"],
                is_active=arm_data.get("is_active", True)
            )
            pool.add_arm(arm)
        return pool

    async def get_or_create(self, experiment_data: dict) -> Agent:
        experiment_id = experiment_data["id"]

        agent = self._cache.get_agent(experiment_id)
        if agent is not None:
            return agent

        protocol_name = experiment_data["protocol"]
        protocol_cls = PROTOCOL_MAP.get(protocol_name)
        if protocol_cls is None:
            raise ValueError(f"Unknown protocol: {protocol_name}. Available: {list(PROTOCOL_MAP.keys())}")

        if self._param_backend.get(experiment_id) is None:
            await self._param_backend.update_cache(experiment_id, protocol_cls)

        pool = self._build_pool(experiment_data["pool"])

        agent = Agent(
            experiment_id=experiment_id,
            pool=pool,
            protocol=protocol_cls,
            init_params=experiment_data.get("protocol_params", {}),
            param_backend=self._param_backend
        )

        self._cache.set_agent(experiment_id, agent)
        return agent
