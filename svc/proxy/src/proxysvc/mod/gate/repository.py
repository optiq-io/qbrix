from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from qbrixstore.postgres.models import Experiment
from qbrixstore.postgres.models import FeatureGate

from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.model.base import ArmConfig
from proxysvc.mod.gate.model.base import BaseArmModel
from proxysvc.mod.gate.model.experiment import ActiveHoursConfig
from proxysvc.mod.gate.model.experiment import ActivePeriodConfig
from proxysvc.mod.gate.model.experiment import ExperimentConfig
from proxysvc.mod.gate.model.experiment import RolloutConfig
from proxysvc.mod.gate.model.experiment import ScheduleConfig
from proxysvc.mod.gate.model.rule import Rule
from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.util import _parse_datetime
from proxysvc.util import _parse_time

_PATCH_PARSERS = {
    "schedule_start": _parse_datetime,
    "schedule_end": _parse_datetime,
    "active_hours_start": _parse_time,
    "active_hours_end": _parse_time,
}


class FeatureGateRepository:
    """repository for feature gate CRUD and transformation to pydantic config.

    the tenant is held on the instance rather than passed per call, matching
    PoolRepository and ExperimentRepository. a gate carries no tenant column of
    its own — it inherits one through its experiment — so every lookup here has
    to join. holding the tenant makes that join the only way to reach a row,
    rather than something each new method has to remember.
    """

    def __init__(self, session: AsyncSession, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    async def get(
        self, experiment_id: str, *, for_update: bool = False
    ) -> FeatureGate | None:
        """get feature gate by experiment id, scoped to the tenant."""
        stmt = (
            select(FeatureGate)
            .join(Experiment, Experiment.id == FeatureGate.experiment_id)
            .options(selectinload(FeatureGate.default_arm))
            .where(FeatureGate.experiment_id == experiment_id)
            .where(Experiment.tenant_id == self._tenant_id)
        )
        if for_update:
            stmt = stmt.with_for_update(of=FeatureGate)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def exists(self, experiment_id: str) -> bool:
        """true if the experiment already has a gate, within the tenant.

        `experiment_id` is unique on the table, so a create against an experiment
        that has one fails on the constraint. this turns that into a conflict the
        caller can name rather than an integrity error.
        """
        stmt = (
            select(FeatureGate.id)
            .join(Experiment, Experiment.id == FeatureGate.experiment_id)
            .where(FeatureGate.experiment_id == experiment_id)
            .where(Experiment.tenant_id == self._tenant_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def owns_experiment(self, experiment_id: str) -> bool:
        """true if the experiment belongs to the tenant.

        create is the one path a gate-ownership check cannot protect: there is no
        gate yet to join through, so without this a create against another
        tenant's experiment id would attach a gate to their experiment.
        """
        stmt = (
            select(Experiment.id)
            .where(Experiment.id == experiment_id)
            .where(Experiment.tenant_id == self._tenant_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create(
        self, experiment_id: str, config: GateConfigRequest
    ) -> FeatureGate:
        """create a new feature gate from typed config."""
        gate = FeatureGate(
            experiment_id=experiment_id,
            enabled=config.enabled,
            rollout_percentage=config.rollout_percentage,
            default_arm_id=config.default_arm_id,
            schedule_start=_parse_datetime(config.schedule_start),
            schedule_end=_parse_datetime(config.schedule_end),
            active_hours_start=_parse_time(config.active_hours_start),
            active_hours_end=_parse_time(config.active_hours_end),
            timezone=config.timezone,
            rules=[r.model_dump() for r in config.rules] if config.rules else [],
            version=1,
        )
        self._session.add(gate)
        await self._session.flush()
        await self._load_default_arm(gate)
        return gate

    async def update(
        self, experiment_id: str, config: GateConfigRequest
    ) -> FeatureGate | None:
        """update feature gate fields with explicit assignment, incrementing version.

        explicit assignment (rather than iterating config keys) ensures nullable
        fields like schedule_start can be cleared to NULL by passing None.
        """
        gate = await self.get(experiment_id)
        if gate is None:
            return None

        gate.enabled = config.enabled
        gate.rollout_percentage = config.rollout_percentage
        gate.default_arm_id = config.default_arm_id
        gate.schedule_start = _parse_datetime(config.schedule_start)
        gate.schedule_end = _parse_datetime(config.schedule_end)
        gate.active_hours_start = _parse_time(config.active_hours_start)
        gate.active_hours_end = _parse_time(config.active_hours_end)
        gate.timezone = config.timezone
        gate.rules = [r.model_dump() for r in config.rules] if config.rules else []
        gate.version += 1
        await self._session.flush()
        await self._load_default_arm(gate)
        return gate

    async def patch(
        self, experiment_id: str, changes: dict[str, Any]
    ) -> FeatureGate | None:
        """apply only the supplied fields, leaving the rest of the gate as stored.

        the row is locked for the read-modify-write so two concurrent patches of
        disjoint fields cannot lose one another. gate writes are rare, so the
        lock costs nothing that matters.
        """
        gate = await self.get(experiment_id, for_update=True)
        if gate is None:
            return None

        for name, value in changes.items():
            parse = _PATCH_PARSERS.get(name)
            setattr(gate, name, parse(value) if parse else value)
        gate.version += 1
        await self._session.flush()
        await self._load_default_arm(gate)
        return gate

    async def _load_default_arm(self, gate: FeatureGate) -> None:
        """re-resolve the default_arm relationship against the current fk.

        observed on `update()`: `get()` eager-loads `default_arm`, so assigning a
        new `default_arm_id` leaves the loaded relationship stale — sqlalchemy
        does not re-resolve it on flush. `to_config()` reads the relationship,
        not the column, so the committed arm came back empty while postgres held
        the right fk.

        that was not just a wrong response. the same config is written to redis,
        and committing sets rollout to 0, which puts *every* request out of
        rollout — so the select path would have served an arm with a null id to
        all traffic.

        `create()` does not exhibit it (a new instance resolves correctly after
        flush) but calls this too: both paths should be explicitly right rather
        than one of them incidentally so. gate writes are rare, so the extra
        select costs nothing that matters.
        """
        await self._session.refresh(gate, attribute_names=["default_arm"])

    async def delete(self, experiment_id: str) -> bool:
        """delete feature gate by experiment id."""
        gate = await self.get(experiment_id)
        if gate is None:
            return False
        await self._session.delete(gate)
        await self._session.flush()
        return True

    @staticmethod
    def to_config(gate: FeatureGate) -> FeatureGateConfig:
        """transform postgres feature gate to pydantic config."""
        tz = ZoneInfo(gate.timezone) if gate.timezone else ZoneInfo("UTC")

        committed_arm = BaseArmModel()
        if gate.default_arm:
            committed_arm = BaseArmModel(
                id=gate.default_arm.id,
                name=gate.default_arm.name,
                index=gate.default_arm.index,
            )

        experiment = ExperimentConfig(
            experiment_id=gate.experiment_id,
            arm=ArmConfig(committed=committed_arm),
            rollout=RolloutConfig(percentage=gate.rollout_percentage),
            schedule=ScheduleConfig(
                hour=ActiveHoursConfig(
                    start=gate.active_hours_start,
                    end=gate.active_hours_end,
                    timezone=tz,
                ),
                period=ActivePeriodConfig(
                    start=gate.schedule_start, end=gate.schedule_end, timezone=tz
                ),
            ),
            updated_at=gate.updated_at,
            version=gate.version,
        )

        rules = []
        for r in gate.rules or []:
            rule_arm = None
            if r.get("arm_id"):
                rule_arm = ArmConfig(
                    committed=BaseArmModel(id=r["arm_id"], name=r.get("arm_name"))
                )
            rules.append(
                Rule(
                    key=r["key"],
                    operator=r["operator"],
                    value=r["value"],
                    arm=rule_arm,
                )
            )

        return FeatureGateConfig(
            enabled=gate.enabled,
            experiment=experiment,
            rules=rules,
            updated_at=gate.updated_at,
            version=gate.version,
        )
