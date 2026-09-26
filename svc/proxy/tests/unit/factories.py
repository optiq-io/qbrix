"""shared test factories for proxysvc unit tests."""

from __future__ import annotations

from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.model.base import BaseArmModel, ArmConfig
from proxysvc.mod.gate import (
    ExperimentConfig,
    RolloutConfig,
    ScheduleConfig,
)
from proxysvc.mod.gate.model.rule import Rule


def make_gate_config(
    experiment_id: str = "exp-1",
    enabled: bool = True,
    rollout_percentage: float = 100.0,
    committed_arm: BaseArmModel | None = None,
    rules: list[Rule] | None = None,
    schedule_active: bool = True,
) -> FeatureGateConfig:
    """factory to build FeatureGateConfig with sensible defaults."""
    if committed_arm is None:
        committed_arm = BaseArmModel(name="default", id="arm-0", index=0)

    arm_config = ArmConfig(committed=committed_arm)

    schedule = ScheduleConfig()

    experiment = ExperimentConfig(
        experiment_id=experiment_id,
        arm=arm_config,
        rollout=RolloutConfig(percentage=rollout_percentage),
        schedule=schedule,
    )

    return FeatureGateConfig(
        enabled=enabled,
        experiment=experiment,
        rules=rules or [],
    )


def make_rule(
    key: str = "region",
    operator: str = "eq",
    value: str = "us",
    committed_arm: BaseArmModel | None = None,
) -> Rule:
    """factory to build a Rule with sensible defaults."""
    if committed_arm is None:
        committed_arm = BaseArmModel(name="rule-arm", id="arm-r", index=1)
    return Rule(
        key=key,
        operator=operator,  # noqa
        value=value,
        arm=ArmConfig(committed=committed_arm),
    )
