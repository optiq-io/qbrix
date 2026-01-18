from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qbrixstore.postgres.models import Pool, Arm, Experiment, FeatureGate


class PoolRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, name: str, arms: list[dict]) -> Pool:
        pool = Pool(name=name)
        for i, arm_data in enumerate(arms):
            arm = Arm(
                name=arm_data["name"],
                index=i,
                metadata_=arm_data.get("metadata", {})
            )
            pool.arms.append(arm)
        self._session.add(pool)
        await self._session.flush()
        return pool

    async def get(self, pool_id: str) -> Pool | None:
        stmt = select(Pool).options(selectinload(Pool.arms)).where(Pool.id == pool_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Pool | None:
        stmt = select(Pool).options(selectinload(Pool.arms)).where(Pool.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, pool_id: str) -> bool:
        pool = await self.get(pool_id)
        if pool is None:
            return False
        await self._session.delete(pool)
        await self._session.flush()
        return True


class ExperimentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        name: str,
        pool_id: str,
        protocol: str,
        protocol_params: dict,
        enabled: bool,
        feature_gate_config: dict | None = None
    ) -> Experiment:
        experiment = Experiment(
            name=name,
            pool_id=pool_id,
            protocol=protocol,
            protocol_params=protocol_params,
            enabled=enabled
        )

        if feature_gate_config:
            feature_gate = FeatureGate(
                rollout_percentage=feature_gate_config.get("rollout_percentage", 1.0),
                default_arm_id=feature_gate_config.get("default_arm_id"),
                schedule_start=feature_gate_config.get("schedule_start"),
                schedule_end=feature_gate_config.get("schedule_end"),
                rules=feature_gate_config.get("rules", [])
            )
            experiment.feature_gate = feature_gate

        self._session.add(experiment)
        await self._session.flush()
        return experiment

    async def get(self, experiment_id: str) -> Experiment | None:
        stmt = (
            select(Experiment)
            .options(
                selectinload(Experiment.pool).selectinload(Pool.arms),
                selectinload(Experiment.feature_gate)
            )
            .where(Experiment.id == experiment_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Experiment | None:
        stmt = (
            select(Experiment)
            .options(
                selectinload(Experiment.pool).selectinload(Pool.arms),
                selectinload(Experiment.feature_gate)
            )
            .where(Experiment.name == name)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, experiment_id: str, **kwargs) -> Experiment | None:
        experiment = await self.get(experiment_id)
        if experiment is None:
            return None

        for key, value in kwargs.items():
            if hasattr(experiment, key) and value is not None:
                setattr(experiment, key, value)

        await self._session.flush()
        return experiment

    async def delete(self, experiment_id: str) -> bool:
        experiment = await self.get(experiment_id)
        if experiment is None:
            return False
        await self._session.delete(experiment)
        await self._session.flush()
        return True
