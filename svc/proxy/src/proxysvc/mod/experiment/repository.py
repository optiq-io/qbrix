from __future__ import annotations

from typing import List

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qbrixstore.postgres.models import Experiment
from qbrixstore.postgres.models import FeatureGate
from qbrixstore.postgres.models import Pool

from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.util import _parse_datetime
from proxysvc.util import _parse_time


class ExperimentRepository:

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def create(
        self,
        name: str,
        pool_id: str,
        policy: str,
        policy_params: dict,
        enabled: bool,
        feature_gate_config: GateConfigRequest | None = None,
        meta_experiment_id: str | None = None,
    ) -> Experiment:
        experiment = Experiment(
            name=name,
            tenant_id=self._tenant_id,
            pool_id=pool_id,
            policy=policy,
            policy_params=policy_params,
            enabled=enabled,
            meta_experiment_id=meta_experiment_id,
        )

        if feature_gate_config:
            feature_gate = FeatureGate(
                enabled=feature_gate_config.enabled,
                rollout_percentage=feature_gate_config.rollout_percentage,
                default_arm_id=feature_gate_config.default_arm_id,
                schedule_start=_parse_datetime(feature_gate_config.schedule_start),
                schedule_end=_parse_datetime(feature_gate_config.schedule_end),
                active_hours_start=_parse_time(feature_gate_config.active_hours_start),
                active_hours_end=_parse_time(feature_gate_config.active_hours_end),
                timezone=feature_gate_config.timezone,
                rules=(
                    [r.model_dump() for r in feature_gate_config.rules]
                    if feature_gate_config.rules
                    else []
                ),
                version=1,
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
                selectinload(Experiment.feature_gate),
            )
            .where(
                Experiment.id == experiment_id, Experiment.tenant_id == self._tenant_id
            )
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Experiment | None:
        stmt = (
            select(Experiment)
            .options(
                selectinload(Experiment.pool).selectinload(Pool.arms),
                selectinload(Experiment.feature_gate),
            )
            .where(Experiment.name == name, Experiment.tenant_id == self._tenant_id)
        )
        response = await self._session.execute(stmt)
        return response.scalar_one_or_none()

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

    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
        enabled: bool | None = None,
    ) -> list[Experiment]:
        stmt = (
            select(Experiment)
            .options(
                selectinload(Experiment.pool).selectinload(Pool.arms),
                selectinload(Experiment.feature_gate),
            )
            .where(
                Experiment.tenant_id == self._tenant_id,
                Experiment.meta_experiment_id.is_(None),  # exclude learner experiments
            )
        )

        if search:
            stmt = stmt.where(Experiment.name.ilike(f"%{search}%"))

        if enabled is not None:
            stmt = stmt.where(Experiment.enabled == enabled)

        stmt = stmt.order_by(Experiment.created_at.desc()).limit(limit).offset(offset)
        response = await self._session.execute(stmt)
        return list(response.scalars().all())

    async def count_active(self) -> int:
        """count enabled experiments for this tenant (excludes meta-bandit learners)."""
        stmt = (
            select(func.count())
            .select_from(Experiment)
            .where(
                Experiment.tenant_id == self._tenant_id,
                Experiment.enabled == True,
                Experiment.meta_experiment_id.is_(
                    None
                ),  # exclude learners from plan limits
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_by_pool(self, pool_id: str) -> List[Experiment]:
        stmt = (
            select(Experiment)
            .options(
                selectinload(Experiment.pool).selectinload(Pool.arms),
                selectinload(Experiment.feature_gate),
            )
            .where(
                Experiment.tenant_id == self._tenant_id,
                Experiment.pool_id == pool_id,
            )
            .order_by(Experiment.created_at.desc())
        )
        response = await self._session.execute(stmt)
        return list(response.scalars().all())
