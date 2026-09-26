from typing import ClassVar, Union

import numpy as np
from pydantic import Field, model_validator

from qbrixcore.param.var import ArrayParam
from qbrixcore.param.var import UserConfigurable
from qbrixcore.param.state import BaseParamState
from qbrixcore.policy.base import BasePolicy
from qbrixcore.policy._reward_type import RewardType
from qbrixcore.context import Context


class EXP3ParamState(BaseParamState):
    """Parameter state for EXP3 (Exponential-weight) policy."""

    gamma: UserConfigurable[float] = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Mixing parameter controlling exploration-exploitation tradeoff. "
        "Higher values (0.2-0.5) explore more, lower values (0.01-0.1) exploit more. "
        "For adversarial environments with high uncertainty, use 0.2-0.3. "
        "For more stable environments with small variations, use 0.05-0.1. Leave empty to use default of 0.1.",
    )
    w: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.w is None:
            self.w = np.ones(self.num_arms, dtype=np.float64)
        return self


class EXP3Policy(BasePolicy):
    """
    EXP3 (Exponential-weight algorithm for Exploration and Exploitation)
    policy for adversarial multi-armed bandit.

    EXP3 maintains weights for each arm and uses importance-weighted
    reward estimates to update them. The gamma parameter controls
    the exploration-exploitation tradeoff.
    """

    name: ClassVar[str] = "EXP3Policy"
    category: ClassVar[str] = "adversarial"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY, RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = EXP3ParamState

    @staticmethod
    def _proba(ps: EXP3ParamState) -> np.ndarray:
        """Compute selection probabilities."""
        return (1.0 - ps.gamma) * (ps.w / ps.w.sum()) + (ps.gamma / ps.num_arms)

    @staticmethod
    def select(ps: EXP3ParamState, context: Context) -> int:
        """Arm selection using EXP3."""
        return int(np.random.choice(ps.num_arms, p=EXP3Policy._proba(ps)))

    @classmethod
    def train(
        cls,
        ps: EXP3ParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> EXP3ParamState:
        """Update weights with importance-weighted reward estimate."""
        proba = cls._proba(ps)

        # importance-weighted reward estimate
        rewards = np.zeros(ps.num_arms)
        rewards[choice] = reward
        estimate = rewards / proba

        # update weights
        new_w = ps.w.copy()
        new_w *= np.exp(estimate * ps.gamma / ps.num_arms)
        new_w /= np.sum(new_w)  # normalize to prevent overflow

        return ps.model_copy(update={"w": new_w})


# ---------------------------------------------------------------------------
# EXP3-IX (adversarial, implicit exploration)
# ---------------------------------------------------------------------------


class EXP3IXParamState(BaseParamState):
    """Parameter state for EXP3-IX (Implicit Exploration) policy."""

    gamma: UserConfigurable[float] = Field(
        default=0.1,
        gt=0.0,
        le=1.0,
        description="Implicit exploration parameter added to probabilities in the denominator "
        "of reward estimates. Controls the bias-variance tradeoff: higher values (0.2-0.5) "
        "give more stable but biased estimates, lower values (0.01-0.1) are less biased "
        "but noisier. For most problems, use 0.05-0.1. "
        "Leave empty to use default of 0.1.",
    )
    eta: UserConfigurable[float] = Field(
        default=0.1,
        gt=0.0,
        le=1.0,
        description="Learning rate for exponential weight updates. "
        "Higher values (0.2-0.5) adapt faster but may oscillate, "
        "lower values (0.01-0.05) are more stable. "
        "For known horizon T with K arms, optimal is sqrt(2*log(K)/(K*T)). "
        "Leave empty to use default of 0.1.",
    )
    w: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.w is None:
            self.w = np.ones(self.num_arms, dtype=np.float64)
        return self


class EXP3IXPolicy(BasePolicy):
    """
    EXP3-IX (Implicit Exploration) policy for adversarial multi-armed bandit.

    Based on "Explore no more: Improved finite-time analysis of the EXP3
    algorithm" by Neu (2015).

    Improves on EXP3 by replacing importance-weighted reward estimates with
    implicitly-explored estimates that add gamma to the denominator:

        r_hat_i = r_i / (p_i + gamma)    instead of    r_hat_i = r_i / p_i

    This prevents reward estimates from blowing up when arm probabilities are
    small, giving much better numerical stability in practice while maintaining
    the same theoretical regret guarantees.
    """

    name: ClassVar[str] = "EXP3IXPolicy"
    category: ClassVar[str] = "adversarial"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY, RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = EXP3IXParamState

    @staticmethod
    def _proba(ps: EXP3IXParamState) -> np.ndarray:
        """Compute selection probabilities (no mixing, pure weight-based)."""
        return ps.w / ps.w.sum()

    @staticmethod
    def select(ps: EXP3IXParamState, context: Context) -> int:
        """Arm selection using EXP3-IX."""
        return int(np.random.choice(ps.num_arms, p=EXP3IXPolicy._proba(ps)))

    @classmethod
    def train(
        cls,
        ps: EXP3IXParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> EXP3IXParamState:
        """Update weights with implicitly-explored reward estimate."""
        proba = cls._proba(ps)

        # implicit exploration: gamma in denominator prevents blowup
        estimate = np.zeros(ps.num_arms)
        estimate[choice] = reward / (proba[choice] + ps.gamma)

        # exponential weight update
        new_w = ps.w.copy()
        new_w *= np.exp(ps.eta * estimate)
        new_w /= np.sum(new_w)  # normalize to prevent overflow

        return ps.model_copy(update={"w": new_w})
