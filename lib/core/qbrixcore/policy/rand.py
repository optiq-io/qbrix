import random as _random
from typing import ClassVar, Union

import numpy as np

from qbrixcore.param.state import BaseParamState
from qbrixcore.policy.base import BasePolicy
from qbrixcore.policy._reward_type import RewardType
from qbrixcore.context import Context


class RandomParamState(BaseParamState):
    """Parameter state for Random (uniform) policy.

    No learnable parameters — only num_arms is needed.
    """

    pass


class RandomPolicy(BasePolicy):
    """
    Uniform random policy for baseline experiments.

    Selects arms uniformly at random with no learning. Useful as:
    - A/B testing baseline (equal traffic split across all arms)
    - Holdout control group for evaluating learning policies
    - Warm-start data collection before switching to a learning policy
    - Sanity check that a learning policy outperforms random
    """

    name: ClassVar[str] = "RandomPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [
        RewardType.BINARY,
        RewardType.BOUNDED,
        RewardType.CONTINUOUS,
    ]
    param_state_cls: type[BaseParamState] = RandomParamState

    @staticmethod
    def select(ps: RandomParamState, context: Context) -> int:
        """Uniform random arm selection."""
        return _random.randrange(ps.num_arms)

    @classmethod
    def train(
        cls,
        ps: RandomParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> RandomParamState:
        """No-op — random policy does not learn."""
        return ps
