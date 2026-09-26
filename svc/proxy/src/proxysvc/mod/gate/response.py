from __future__ import annotations

from typing import Any
from typing import List
from typing import Optional

from pydantic import BaseModel

from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.controller import ExperimentFlagState
from proxysvc.mod.gate.controller import GateDecision


class GateRuleResponse(BaseModel):
    key: str
    operator: str
    value: Any
    arm_id: Optional[str] = None
    arm_name: Optional[str] = None


class GateConfigResponse(BaseModel):
    experiment_id: str
    enabled: bool = True
    rollout_percentage: float = 100.0
    default_arm_id: Optional[str] = None
    default_arm_name: Optional[str] = None
    schedule_start: Optional[str] = None
    schedule_end: Optional[str] = None
    active_hours_start: Optional[str] = None
    active_hours_end: Optional[str] = None
    timezone: str = "UTC"
    rules: List[GateRuleResponse] = []
    updated_at: Optional[str] = None
    version: int = 1


def to_response(config: FeatureGateConfig) -> GateConfigResponse:
    """transform a FeatureGateConfig into a flat GateConfigResponse for the API."""
    exp = config.experiment
    arm = exp.arm.committed
    return GateConfigResponse(
        experiment_id=exp.experiment_id,
        enabled=config.enabled,
        rollout_percentage=exp.rollout.percentage,
        default_arm_id=arm.id,
        default_arm_name=arm.name,
        schedule_start=(
            exp.schedule.period.start.isoformat() if exp.schedule.period.start else None
        ),
        schedule_end=(
            exp.schedule.period.end.isoformat() if exp.schedule.period.end else None
        ),
        active_hours_start=(
            exp.schedule.hour.start.strftime("%H:%M")
            if exp.schedule.hour.start
            else None
        ),
        active_hours_end=(
            exp.schedule.hour.end.strftime("%H:%M") if exp.schedule.hour.end else None
        ),
        timezone=str(exp.schedule.hour.timezone),
        rules=[
            GateRuleResponse(
                key=r.key,
                operator=str(r.operator),
                value=r.value,
                arm_id=r.arm.committed.id if r.arm and r.arm.committed else None,
                arm_name=r.arm.committed.name if r.arm and r.arm.committed else None,
            )
            for r in config.rules
        ],
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
        version=config.version,
    )


class GateRuleEvaluation(BaseModel):
    key: str
    operator: str
    value: Any
    matched: bool
    # the rule that decided the outcome, when one did
    decisive: bool = False


class GateEvaluateResponse(BaseModel):
    """the gate's decision for a sample context, and why.

    `eligible` is true when the bandit would select — i.e. the gate declined to
    force an arm. it is deliberately not a synonym for "passed the rules": a
    context outside the rollout is ineligible even with every rule matching.
    """

    eligible: bool
    reason: str  # disabled | blackout | rollout | rule | bandit
    arm_id: Optional[str] = None
    arm_name: Optional[str] = None
    enabled: bool
    in_schedule: bool
    in_rollout: bool
    rollout_percentage: float
    rules: List[GateRuleEvaluation] = []


def to_evaluation(
    config: FeatureGateConfig, decision: GateDecision
) -> GateEvaluateResponse:
    """flatten a GateDecision for the API."""
    state = decision.state
    rules = config.rules or []
    matches = decision.rule_matches

    return GateEvaluateResponse(
        eligible=decision.arm is None,
        reason=decision.reason,
        arm_id=decision.arm.id if decision.arm else None,
        arm_name=decision.arm.name if decision.arm else None,
        enabled=config.enabled,
        in_schedule=bool(ExperimentFlagState.ACTIVE & state),
        in_rollout=bool(ExperimentFlagState.RPOS & state),
        rollout_percentage=config.experiment.rollout.percentage,
        rules=[
            GateRuleEvaluation(
                key=rule.key,
                operator=str(rule.operator),
                value=rule.value,
                matched=matches[i] if i < len(matches) else False,
                decisive=decision.matched_rule == i,
            )
            for i, rule in enumerate(rules)
        ],
    )
