from typing import ClassVar, Union
import random

from pydantic import Field, model_validator
import numpy as np

from qbrixcore.param.var import ArrayParam
from qbrixcore.param.var import UserConfigurable
from qbrixcore.param.state import BaseParamState
from qbrixcore.policy.base import BasePolicy
from qbrixcore.policy._reward_type import RewardType
from qbrixcore.context import Context
from qbrixcore.policy._math import argmax_random_tiebreak


class EpsilonParamState(BaseParamState):
    eps: UserConfigurable[float] = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Initial exploration rate. Set to 0.1 for 10% exploration (balanced), 0.3 for more exploration "
        "in uncertain environments, or 0.01 for mostly exploitation in stable environments. "
        "Must be between 0 and 1.",
    )
    gamma: UserConfigurable[float] = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Decay rate that controls how quickly exploration decreases over time. gamma=0.0 means no decay "
        "(constant eps), gamma=0.02 gives slow decay, gamma=0.1 gives moderate decay, gamma=0.5 gives fast decay. "
        "Must be between 0 and 1.",
    )
    mu: ArrayParam | None = None
    T: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.mu is None:
            self.mu = np.zeros(self.num_arms, dtype=np.float64)
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        return self


class EpsilonPolicy(BasePolicy):

    name: ClassVar[str] = "EpsilonPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [
        RewardType.BINARY,
        RewardType.BOUNDED,
        RewardType.CONTINUOUS,
    ]
    param_state_cls: type[BaseParamState] = EpsilonParamState

    @staticmethod
    def decay(ps: EpsilonParamState):
        """
        Thread-safe epsilon decay using exponential decay.

        Formula: eps_new = eps_old * (1 - gamma)

        Examples:
        - gamma=0.0: No decay (eps stays constant)
        - gamma=0.01: Slow decay (1% reduction per step)
        - gamma=0.1: Medium decay (10% reduction per step)
        - gamma=0.5: Fast decay (50% reduction per step)
        """
        ps.eps *= 1 - ps.gamma
        return ps

    @staticmethod
    def select(ps: EpsilonParamState, context: Context):
        if random.random() > ps.eps:
            return argmax_random_tiebreak(ps.mu)
        else:
            return random.choice(range(ps.num_arms))

    @classmethod
    def train(
        cls,
        ps: EpsilonParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> EpsilonParamState:

        new_T = ps.T.copy()
        new_mu = ps.mu.copy()

        new_T[choice] += 1
        new_mu[choice] += (reward - ps.mu[choice]) / new_T[choice]
        new_eps = ps.eps * (1 - ps.gamma)

        return ps.model_copy(
            update={
                "T": new_T,
                "mu": new_mu,
                "eps": new_eps,
            }
        )
