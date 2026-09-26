from __future__ import annotations

from typing import ClassVar, Union

import numpy as np
from pydantic import Field, model_validator

from qbrixcore.param.var import ArrayParam
from qbrixcore.param.state import BaseParamState
from qbrixcore.policy.base import BasePolicy
from qbrixcore.policy._reward_type import RewardType
from qbrixcore.context import Context

_POLICY_REGISTRY: dict[str, type[BasePolicy]] | None = None


def _get_policy_class(name: str) -> type[BasePolicy]:
    """lazy-resolve a policy class by name from the policy registry."""
    global _POLICY_REGISTRY
    if _POLICY_REGISTRY is None:
        from qbrixcore.policy import POLICIES

        _POLICY_REGISTRY = {p.name: p for p in POLICIES}
    cls = _POLICY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown meta_policy: {name}")
    return cls


class MetaBanditParamState(BaseParamState):
    """parameter state for the meta-bandit policy.

    uses EXP3 at the meta-level to select among learner algorithms.
    EXP3 is distribution-free — no reward type or context dimension
    needed for the meta-level decision.
    """

    learners: list[str] = Field(
        default_factory=list,
        description="ordered list of learner experiment ids.",
    )
    gamma: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="EXP3 mixing parameter controlling exploration-exploitation.",
    )
    w: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        m = self.num_arms
        if self.w is None:
            self.w = np.ones(m, dtype=np.float64)
        return self


class MetaBanditPolicy(BasePolicy):
    """meta-bandit policy for automatic algorithm selection.

    maintains a portfolio of learner bandit algorithms and adaptively routes
    traffic toward the best-performing one. delegates to EXP3 at the
    meta-level, which is distribution-free and needs no knowledge of reward
    type or context dimension.

    the sqrt(T) regret of EXP3 at the meta-level is acceptable because:
    - meta-level has only M=4 arms (learner algorithms), not K content arms
    - the meta-level regret is relative to the best learner, which itself
      achieves near-optimal regret on the actual K-arm problem
    """

    name: ClassVar[str] = "MetaBanditPolicy"
    category: ClassVar[str] = "meta"
    reward_types: ClassVar[list[RewardType]] = [
        RewardType.BINARY,
        RewardType.BOUNDED,
        RewardType.CONTINUOUS,
    ]
    param_state_cls: type[BaseParamState] = MetaBanditParamState

    @classmethod
    def build_state(cls, **params) -> MetaBanditParamState:
        learners = params.get("learners", [])
        params.pop("num_arms", None)
        return cls.param_state_cls(
            num_arms=len(learners),
            **params,
        )

    @staticmethod
    def select(ps: MetaBanditParamState, context: Context) -> int:
        """select a learner algorithm index via EXP3."""
        inner_cls = _get_policy_class("EXP3Policy")
        return inner_cls.select(ps, context)

    @classmethod
    def train(
        cls,
        ps: MetaBanditParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> MetaBanditParamState:
        """update meta-level weights via EXP3."""
        inner_cls = _get_policy_class("EXP3Policy")
        return inner_cls.train(ps, context, choice, reward)


_CANDIDATES: list[dict] = [
    # --- non-contextual: stationary stochastic -------------------------
    {
        "policy": "BetaTSPolicy",
        "policy_params": {},
        "reward_types": {"binary", "bounded"},
        "contextual": False,
    },
    {
        "policy": "UCB1TunedPolicy",
        "policy_params": {},
        "reward_types": {"bounded"},
        "contextual": False,
    },
    {
        "policy": "KLUCBPolicy",
        "policy_params": {},
        "reward_types": {"binary", "bounded"},
        "contextual": False,
    },
    {
        "policy": "GaussianTSPolicy",
        "policy_params": {},
        "reward_types": {"continuous"},
        "contextual": False,
    },
    # --- non-contextual: non-stationary --------------------------------
    {
        "policy": "DiscountedTSPolicy",
        "policy_params": {"gamma": 0.9999},
        "reward_types": {"binary", "bounded"},
        "contextual": False,
    },
    {
        "policy": "DiscountedTSPolicy",
        "policy_params": {"gamma": 0.999},
        "reward_types": {"binary", "bounded"},
        "contextual": False,
    },
    # --- non-contextual: many-arm efficient ----------------------------
    {
        "policy": "MOSSAnyTimePolicy",
        "policy_params": {},
        "reward_types": {"bounded"},
        "contextual": False,
    },
    # --- non-contextual: simple baselines ------------------------------
    {
        "policy": "EpsilonPolicy",
        "policy_params": {"eps": 0.15, "gamma": 0.001},
        "reward_types": {"binary", "bounded", "continuous"},
        "contextual": False,
    },
    {
        "policy": "EpsilonPolicy",
        "policy_params": {"eps": 0.3, "gamma": 0.01},
        "reward_types": {"binary", "bounded", "continuous"},
        "contextual": False,
    },
    # --- non-contextual: adversarial safety ----------------------------
    {
        "policy": "EXP3IXPolicy",
        "policy_params": {"gamma": 0.05, "eta": 0.1},
        "reward_types": {"binary", "bounded"},
        "contextual": False,
    },
    {
        "policy": "FPLPolicy",
        "policy_params": {},
        "reward_types": {"continuous"},
        "contextual": False,
    },
    # --- contextual: linear models -------------------------------------
    {
        "policy": "LinTSPolicy",
        "policy_params": {"v": 1.0},
        "reward_types": {"binary", "bounded", "continuous"},
        "contextual": True,
    },
    {
        "policy": "LinTSPolicy",
        "policy_params": {"v": 0.25},
        "reward_types": {"binary", "bounded", "continuous"},
        "contextual": True,
    },
    {
        "policy": "LinUCBPolicy",
        "policy_params": {"alpha": 1.0},
        "reward_types": {"binary", "bounded", "continuous"},
        "contextual": True,
    },
    # --- contextual: generalised linear (binary only) ------------------
    {
        "policy": "LogisticTSPolicy",
        "policy_params": {},
        "reward_types": {"binary"},
        "contextual": True,
    },
    {
        "policy": "GLMUCBPolicy",
        "policy_params": {"alpha": 1.0},
        "reward_types": {"binary"},
        "contextual": True,
    },
]


# attention: duplicate, already defined in RewardType
_VALID_REWARD_TYPES = {"binary", "bounded", "continuous"}


def build_learners(
    reward_type: str | None = None,
    use_context: bool = False,
    dim: int | None = None,
) -> list[dict]:
    """build a scoped portfolio of learner policies for the meta-bandit.

    filters the canonical candidate table by reward type and contextual
    scope, then merges `dim` into contextual entries. returns a list of
    dicts with keys `policy` and `policy_params` (the shape consumed by
    `_create_auto_experiment`).

    args:
        reward_type: one of "binary", "bounded", "continuous", or None to
            include every reward type.
        use_context: when True, return only contextual policies (which
            require `dim`). when False, return only non-contextual ones.
        dim: context vector dimension, required if `use_context` is True.

    raises:
        ValueError: if `use_context` is True but `dim` is None, if
            `reward_type` is not a valid value, or if the resulting
            portfolio contains fewer than two learners (auto mode needs
            at least two arms at the meta level to have anything to
            select between).
    """
    if reward_type is not None and reward_type not in _VALID_REWARD_TYPES:
        raise ValueError(
            f"invalid reward_type: {reward_type!r} (expected one of {sorted(_VALID_REWARD_TYPES)})"
        )
    if use_context and dim is None:
        raise ValueError("dim is required when use_context=True")
    if use_context and dim is not None and dim <= 0:
        raise ValueError(f"dim must be a positive integer, got {dim}")

    learners: list[dict] = []
    for entry in _CANDIDATES:
        if entry["contextual"] != use_context:
            continue
        if reward_type is not None and reward_type not in entry["reward_types"]:
            continue
        policy_params = dict(entry["policy_params"])
        if use_context:
            policy_params["dim"] = dim
        learners.append(
            {
                "policy": entry["policy"],
                "policy_params": policy_params,
            }
        )

    if len(learners) < 2:
        raise ValueError(
            "no scoped portfolio available for "
            f"reward_type={reward_type!r}, use_context={use_context} "
            f"(only {len(learners)} candidate(s) matched)"
        )
    return learners
