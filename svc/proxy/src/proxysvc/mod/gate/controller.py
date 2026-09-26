from dataclasses import dataclass, field
from enum import Flag, auto
from typing import Optional

from .config import FeatureGateConfig, Rule, BaseArmModel


class ExperimentFlagState(Flag):
    """flags representing the state of an experiment."""

    ENABLED = auto()
    ACTIVE = auto()
    BLACKOUT = auto()
    DISABLED = auto()
    RPOS = auto()  # context is within rollout percentage
    RNEG = auto()  # context is outside rollout percentage


@dataclass
class GateDecision:
    """the outcome of a gate evaluation, plus why.

    `arm is None` means bandit selection proceeds. `reason` names the branch
    that produced the outcome, so a dry run can explain itself without
    re-deriving the logic.
    """

    arm: Optional[BaseArmModel]
    reason: str  # disabled | blackout | rollout | rule | bandit
    state: "ExperimentFlagState"
    matched_rule: Optional[int] = None
    # only populated when tracing; the hot path short-circuits instead
    rule_matches: list[bool] = field(default_factory=list)


class FeatureGate:
    """feature gate controller for experiment-based decision-making."""

    negset = ExperimentFlagState.BLACKOUT | ExperimentFlagState.RNEG

    @classmethod
    def render_feature_flags(
        cls, config: FeatureGateConfig, context_id: str
    ) -> ExperimentFlagState:
        """render experiment state flags based on configuration and context."""
        experiment = config.experiment
        state = ExperimentFlagState(0)

        if config.enabled:
            state |= ExperimentFlagState.ENABLED
        else:
            state |= ExperimentFlagState.DISABLED

        if experiment.schedule.is_in_active_schedule():
            state |= ExperimentFlagState.ACTIVE
        else:
            state |= ExperimentFlagState.BLACKOUT

        if experiment.rollout.is_in_rollout(context_id):
            state |= ExperimentFlagState.RPOS
        else:
            state |= ExperimentFlagState.RNEG

        return state

    @classmethod
    def render_rules(cls, config: FeatureGateConfig, metadata: dict) -> Rule | None:
        """apply rules to metadata and return first matching rule."""
        if not (rules := config.rules):
            return None

        for rule in rules:
            if rule.eval(metadata):
                return rule

        return None

    @classmethod
    def control(
        cls, config: FeatureGateConfig, context_id: str, metadata: dict
    ) -> BaseArmModel | None:
        """determine which arm to return based on experiment state and rules.

        a disabled gate does no gating: bandit selection proceeds. when enabled,
        returns the committed arm in blackout or when context is outside rollout,
        otherwise evaluates rules and returns the matching rule's arm, or None if
        bandit selection should proceed.
        """
        return cls.decide(config, context_id, metadata).arm

    @classmethod
    def decide(
        cls,
        config: FeatureGateConfig,
        context_id: str,
        metadata: dict,
        *,
        trace: bool = False,
    ) -> GateDecision:
        """`control()` with its reasoning exposed.

        the dry-run endpoint and the hot path share this one implementation on
        purpose: a preview that told you something different from what the gate
        actually does would be worse than no preview at all.

        `trace=True` additionally evaluates *every* rule so the caller can show
        which ones passed. the hot path leaves it off and keeps short-circuiting
        — the decision is identical either way, only the reporting differs.
        """
        if not config.enabled:
            return GateDecision(
                arm=None, reason="disabled", state=ExperimentFlagState.DISABLED
            )

        fstate = cls.render_feature_flags(config, context_id)
        rules = config.rules or []
        matches = [r.eval(metadata) for r in rules] if trace else []

        if cls.negset & fstate:
            reason = "blackout" if ExperimentFlagState.BLACKOUT & fstate else "rollout"
            return GateDecision(
                arm=config.experiment.arm.committed,
                reason=reason,
                state=fstate,
                rule_matches=matches,
            )

        index, rule = cls._first_match(rules, metadata, matches if trace else None)
        if rule is not None:
            arm = rule.arm.committed if rule.arm else config.experiment.arm.committed
            return GateDecision(
                arm=arm,
                reason="rule",
                state=fstate,
                matched_rule=index,
                rule_matches=matches,
            )

        return GateDecision(
            arm=None, reason="bandit", state=fstate, rule_matches=matches
        )

    @staticmethod
    def _first_match(
        rules: list[Rule], metadata: dict, precomputed: Optional[list[bool]]
    ) -> tuple[Optional[int], Optional[Rule]]:
        """first matching rule, reusing trace results rather than re-evaluating."""
        for i, rule in enumerate(rules):
            hit = precomputed[i] if precomputed is not None else rule.eval(metadata)
            if hit:
                return i, rule
        return None, None
