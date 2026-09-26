import math
from typing import ClassVar, Union

import numpy as np
from pydantic import Field, model_validator

from qbrixcore.param.var import ArrayParam
from qbrixcore.param.var import UserConfigurable
from qbrixcore.param.state import BaseParamState
from qbrixcore.policy.base import BasePolicy
from qbrixcore.policy._reward_type import RewardType
from qbrixcore.context import Context
from qbrixcore.policy._math import argmax_random_tiebreak
from qbrixcore.policy._math import sigmoid

# ---------------------------------------------------------------------------
# UCB1-Tuned (stochastic, bounded)
# ---------------------------------------------------------------------------


class UCB1TunedParamState(BaseParamState):
    """Parameter state for UCB1-Tuned policy."""

    alpha: UserConfigurable[float] = Field(
        default=2.0,
        gt=0.0,
        description="Exploration parameter controlling confidence interval width. "
        "Higher values (3-5) explore more aggressively, lower values (1-1.5) exploit more. "
        "Good starting point is 2.0. "
        "Leave empty to use default of 2.0.",
    )
    mu: ArrayParam | None = None
    T: ArrayParam | None = None
    rsq: ArrayParam | None = None
    round: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def set_defaults(self):
        if self.mu is None:
            self.mu = np.zeros(self.num_arms, dtype=np.float64)
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        if self.rsq is None:
            self.rsq = np.zeros(self.num_arms, dtype=np.float64)
        return self


class UCB1TunedPolicy(BasePolicy):
    """
    UCB1-Tuned policy for multi-armed bandit.

    Uses variance estimates to compute tighter confidence bounds than UCB1.
    """

    name: ClassVar[str] = "UCB1TunedPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = UCB1TunedParamState

    @staticmethod
    def _arm_var_upper_bound(ps: UCB1TunedParamState, arm: int) -> float:
        """Calculate arm variance upper bound."""
        if ps.T[arm] == 0:
            return float("inf")
        sigma = ps.rsq[arm] / ps.T[arm] - ps.mu[arm] ** 2
        delta = math.sqrt(ps.alpha * math.log(ps.round + 1) / ps.T[arm])
        return float(sigma + delta)

    @staticmethod
    def _upper_bound(ps: UCB1TunedParamState, arm: int) -> float:
        """Calculate upper confidence bound."""
        if ps.T[arm] == 0:
            return float("inf")
        sigma_bound = min(0.25, UCB1TunedPolicy._arm_var_upper_bound(ps, arm))
        return float(
            ps.mu[arm] + math.sqrt(sigma_bound * math.log(ps.round + 1) / ps.T[arm])
        )

    @staticmethod
    def select(ps: UCB1TunedParamState, context: Context) -> int:
        """Arm selection using UCB1-Tuned."""
        # Note: round increment happens in train, use current round for selection
        upper_bounds = [UCB1TunedPolicy._upper_bound(ps, i) for i in range(ps.num_arms)]
        return argmax_random_tiebreak(upper_bounds)

    @classmethod
    def train(
        cls,
        ps: UCB1TunedParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> UCB1TunedParamState:
        """Update state with observed reward."""
        new_T = ps.T.copy()
        new_mu = ps.mu.copy()
        new_rsq = ps.rsq.copy()

        new_T[choice] += 1
        new_rsq[choice] += reward**2
        prev_mu = ps.mu[choice]
        new_mu[choice] += (reward - prev_mu) / new_T[choice]

        return ps.model_copy(
            update={
                "T": new_T,
                "mu": new_mu,
                "rsq": new_rsq,
                "round": ps.round + 1,
            }
        )


# ---------------------------------------------------------------------------
# KL-UCB (stochastic, binary/bounded)
# ---------------------------------------------------------------------------


class KLUCBParamState(BaseParamState):
    """Parameter state for KL-UCB policy."""

    c: UserConfigurable[float] = Field(
        default=0.0,
        ge=0.0,
        description="Exploration bonus coefficient for the log(log(t)) term. "
        "Typically 0 (no additional exploration) or small positive values (0.1-1.0) for problems requiring more exploration. "
        "Most users should leave this at 0.0.",
    )
    tolerance: UserConfigurable[float] = Field(
        default=1e-6,
        gt=0.0,
        description="Convergence tolerance for the KL-divergence binary search. "
        "Smaller values give more precise UCB bounds at the cost of extra iterations. "
        "Most users should leave this at 1e-6.",
    )
    max_iterations: UserConfigurable[int] = Field(
        default=50,
        gt=0,
        description="Maximum number of binary search iterations for computing KL-UCB bounds. "
        "Higher values increase precision but add compute cost. "
        "Most users should leave this at 50.",
    )
    S: ArrayParam | None = None
    N: ArrayParam | None = None
    round: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def set_defaults(self):
        if self.S is None:
            self.S = np.zeros(self.num_arms, dtype=np.float64)
        if self.N is None:
            self.N = np.zeros(self.num_arms, dtype=np.int64)
        return self


class KLUCBPolicy(BasePolicy):
    """
    KL-UCB (Kullback-Leibler Upper Confidence Bound) policy.

    Based on "The KL-UCB Algorithm for Bounded Stochastic Bandits and Beyond"
    by Garivier & Cappe (2011).

    Uses KL-divergence to compute tighter confidence bounds than standard UCB,
    achieving the Lai-Robbins lower bound for Bernoulli rewards.
    """

    name: ClassVar[str] = "KLUCBPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY, RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = KLUCBParamState

    @staticmethod
    def _kl_bernoulli(p: float, q: float) -> float:
        """Compute KL divergence between Bernoulli(p) and Bernoulli(q)."""
        p = np.clip(p, 0.0, 1.0)
        q = np.clip(q, 0.0, 1.0)

        if p == 0.0:
            if q == 1.0:
                return float("inf")
            return -math.log(1.0 - q)

        if p == 1.0:
            if q == 0.0:
                return float("inf")
            return -math.log(q)

        if q == 0.0 or q == 1.0:
            return float("inf")

        return p * math.log(p / q) + (1.0 - p) * math.log((1.0 - p) / (1.0 - q))

    @staticmethod
    def _compute_ucb(ps: KLUCBParamState, arm: int, t: int) -> float:
        """Compute KL-UCB upper confidence bound for an arm."""
        if ps.N[arm] == 0:
            return float("inf")

        p_hat = ps.S[arm] / ps.N[arm]
        n = ps.N[arm]

        if t <= 1:
            threshold = 0.0
        else:
            log_t = math.log(t)
            log_log_t = math.log(log_t) if log_t > 1.0 else 0.0
            threshold = (log_t + ps.c * log_log_t) / n

        if threshold < 1e-10:
            return p_hat

        left, right = p_hat, 1.0

        if KLUCBPolicy._kl_bernoulli(p_hat, right) <= threshold:
            return right

        for _ in range(ps.max_iterations):
            mid = (left + right) / 2.0
            kl_div = KLUCBPolicy._kl_bernoulli(p_hat, mid)

            if abs(kl_div - threshold) < ps.tolerance:
                return mid

            if kl_div < threshold:
                left = mid
            else:
                right = mid

            if abs(right - left) < ps.tolerance:
                break

        return (left + right) / 2.0

    @classmethod
    def select(cls, ps: KLUCBParamState, context: Context) -> int:
        """Arm selection using KL-UCB."""
        t = ps.round + 1
        ucb_values = [cls._compute_ucb(ps, i, t) for i in range(ps.num_arms)]
        return argmax_random_tiebreak(ucb_values)

    @classmethod
    def train(
        cls,
        ps: KLUCBParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> KLUCBParamState:
        """Update state with observed reward."""
        new_N = ps.N.copy()
        new_S = ps.S.copy()

        reward = np.clip(reward, 0.0, 1.0)
        new_N[choice] += 1
        new_S[choice] += reward

        return ps.model_copy(
            update={
                "N": new_N,
                "S": new_S,
                "round": ps.round + 1,
            }
        )


class KLUCBPlusPolicy(KLUCBPolicy):
    """
    KL-UCB+ variant using log(t/N[a]) instead of log(t) in exploration bonus.

    This variant can provide better empirical performance. Inspired by MOSS and DMED+.
    """

    name: ClassVar[str] = "KLUCBPlusPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY, RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = KLUCBParamState

    @staticmethod
    def _compute_ucb(ps: KLUCBParamState, arm: int, t: int) -> float:
        """Compute KL-UCB+ upper confidence bound using log(t/N[arm])."""
        if ps.N[arm] == 0:
            return float("inf")

        p_hat = ps.S[arm] / ps.N[arm]
        n = ps.N[arm]

        ratio = max(t / n, 1.0)
        log_ratio = math.log(ratio)

        if log_ratio <= 0:
            return p_hat

        log_log_ratio = math.log(log_ratio) if log_ratio > 1.0 else 0.0
        threshold = (log_ratio + ps.c * log_log_ratio) / n

        if threshold < 1e-10:
            return p_hat

        left, right = p_hat, 1.0

        if KLUCBPolicy._kl_bernoulli(p_hat, right) <= threshold:
            return right

        for _ in range(ps.max_iterations):
            mid = (left + right) / 2.0
            kl_div = KLUCBPolicy._kl_bernoulli(p_hat, mid)

            if abs(kl_div - threshold) < ps.tolerance:
                return mid

            if kl_div < threshold:
                left = mid
            else:
                right = mid

            if abs(right - left) < ps.tolerance:
                break

        return (left + right) / 2.0


# ---------------------------------------------------------------------------
# LinUCB (contextual, all reward types)
# ---------------------------------------------------------------------------


class LinUCBParamState(BaseParamState):
    """Parameter state for Linear UCB policy."""

    dim: UserConfigurable[int] = Field(
        ...,
        gt=0,
        description="Dimension of the context vector. "
        "This must match the length of context features you provide during selection. "
        "For example, use 5 if you pass [user_age, user_location, time_of_day, device_type, page_views] as context. "
        "Must be a positive integer.",
    )
    alpha: UserConfigurable[float] = Field(
        default=1.5,
        gt=0.0,
        description="Exploration parameter controlling the width of confidence intervals. "
        "Higher values (2-3) explore more, lower values (0.5-1) exploit more aggressively. "
        "Good starting point is 1.5. If you see too much exploration, decrease to 1.0. "
        "If poor arms are selected too often, increase to 2.0-3.0. "
        "Leave empty to use default of 1.5.",
    )
    d: ArrayParam | None = None  # design matrices (num_arms, dim, dim)
    r: ArrayParam | None = None  # reward weighted context sum (num_arms, dim, 1)

    @model_validator(mode="after")
    def set_defaults(self):
        if self.d is None:
            self.d = np.array(
                [np.identity(self.dim, dtype=np.float64) for _ in range(self.num_arms)]
            )
        if self.r is None:
            self.r = np.zeros((self.num_arms, self.dim, 1), dtype=np.float64)
        return self


class LinUCBPolicy(BasePolicy):
    """
    Linear UCB policy for contextual multi-armed bandit.

    Uses ridge regression to estimate reward parameters and adds
    confidence bounds based on the design matrix inverse.
    """

    name: ClassVar[str] = "LinUCBPolicy"
    category: ClassVar[str] = "contextual"
    reward_types: ClassVar[list[RewardType]] = [
        RewardType.BINARY,
        RewardType.BOUNDED,
        RewardType.CONTINUOUS,
    ]
    param_state_cls: type[BaseParamState] = LinUCBParamState

    @staticmethod
    def _reshape_context_vector(context: Context) -> np.ndarray:
        """Reshape context vector to column vector."""
        context_vector = context.vector
        if isinstance(context_vector, list):
            context_vector = np.array(context_vector, dtype=np.float64)
        if context_vector.ndim == 1:
            context_vector = context_vector.reshape(-1, 1)
        return context_vector

    @staticmethod
    def _arm_upper_bound(ps: LinUCBParamState, arm: int, context: np.ndarray) -> float:
        """Calculate upper confidence bound for an arm."""
        try:
            a_inv = np.linalg.inv(ps.d[arm])
            theta = np.dot(a_inv, ps.r[arm])
            mean_estimate = np.dot(theta.T, context)
            confidence_bound = ps.alpha * np.sqrt(
                np.dot(context.T, np.dot(a_inv, context))
            )
            return float((mean_estimate + confidence_bound).item())
        except np.linalg.LinAlgError:
            return float("inf")

    @staticmethod
    def select(ps: LinUCBParamState, context: Context) -> int:
        """Arm selection using Linear UCB."""
        x = LinUCBPolicy._reshape_context_vector(context)
        upper_bounds = [
            LinUCBPolicy._arm_upper_bound(ps, i, x) for i in range(ps.num_arms)
        ]
        return argmax_random_tiebreak(upper_bounds)

    @classmethod
    def train(
        cls,
        ps: LinUCBParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> LinUCBParamState:
        """Update state with observed reward."""
        x = cls._reshape_context_vector(context)
        if x.ndim == 1:
            x = x.reshape(-1, 1)

        new_d = ps.d.copy()
        new_r = ps.r.copy()

        new_d[choice] = ps.d[choice] + np.dot(x, x.T)
        new_r[choice] = ps.r[choice] + reward * x

        return ps.model_copy(
            update={
                "d": new_d,
                "r": new_r,
            }
        )


# ---------------------------------------------------------------------------
# GLM-UCB (contextual, binary)
# ---------------------------------------------------------------------------


class GLMUCBParamState(BaseParamState):
    """Parameter state for GLM-UCB (Logistic UCB) policy.

    Maintains per-arm weight vectors and accumulated diagonal Hessian
    for computing logistic confidence bounds.
    """

    dim: UserConfigurable[int] = Field(
        ...,
        gt=0,
        description="Dimension of the context vector. "
        "This must match the length of context features you provide during selection. "
        "For example, use 5 if you pass [user_age, user_location, time_of_day, device_type, page_views] as context. "
        "Must be a positive integer.",
    )
    alpha: UserConfigurable[float] = Field(
        default=1.5,
        gt=0.0,
        description="Exploration parameter controlling the width of confidence bounds. "
        "Higher values (2-3) explore more aggressively, lower values (0.5-1) exploit sooner. "
        "Start with 1.5. If poor arms are selected too often, increase to 2.0-3.0. "
        "If exploration is excessive, decrease to 1.0. "
        "Leave empty to use default of 1.5.",
    )
    lambda_: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="L2 regularization strength. "
        "Higher values (2-5) prevent overfitting with sparse data, "
        "lower values (0.1-0.5) allow the model to fit more closely. "
        "Start with 1.0. Leave empty to use default of 1.0.",
    )
    lr: UserConfigurable[float] = Field(
        default=0.1,
        gt=0.0,
        le=1.0,
        description="Learning rate for online Newton step updates. "
        "Controls how quickly the model adapts to new observations. "
        "Lower values (0.01-0.05) are more stable, higher values (0.1-0.5) adapt faster. "
        "Start with 0.1. Leave empty to use default of 0.1.",
    )
    w: ArrayParam | None = None  # weight vectors (num_arms, dim)
    h: ArrayParam | None = None  # diagonal Hessian approximation (num_arms, dim)

    @model_validator(mode="after")
    def set_defaults(self):
        if self.w is None:
            self.w = np.zeros((self.num_arms, self.dim), dtype=np.float64)
        if self.h is None:
            self.h = np.full(
                (self.num_arms, self.dim),
                self.lambda_,
                dtype=np.float64,
            )
        return self


class GLMUCBPolicy(BasePolicy):
    """
    GLM-UCB (Logistic UCB) policy for contextual bandits with binary rewards.

    Uses logistic regression with upper confidence bounds for arm selection.
    Unlike LinUCB which assumes linear rewards, GLM-UCB uses the logistic
    link function, making it statistically appropriate for binary outcomes.

    Selection computes: sigmoid(w_a^T x) + alpha * ||x||_{H_a^{-1}}
    where H_a is the accumulated diagonal Hessian for arm a.

    This is the deterministic UCB counterpart to Logistic Thompson Sampling —
    predictable, easy to monitor, and a strong baseline for binary contextual bandits.
    """

    name: ClassVar[str] = "GLMUCBPolicy"
    category: ClassVar[str] = "contextual"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY]
    param_state_cls: type[BaseParamState] = GLMUCBParamState

    @staticmethod
    def _to_vector(context: Context) -> np.ndarray:
        """extract context as 1d numpy array."""
        v = context.vector
        if isinstance(v, list):
            v = np.array(v, dtype=np.float64)
        return v.ravel()

    @staticmethod
    def _arm_upper_bound(ps: GLMUCBParamState, arm: int, x: np.ndarray) -> float:
        """compute upper confidence bound for an arm.

        UCB = sigmoid(w_a^T x) + alpha * ||x||_{H_a^{-1}}
        where ||x||_{H^{-1}} = sqrt(sum(x_i^2 / h_i)) is the
        Mahalanobis norm under the diagonal Hessian inverse.
        """
        logit = np.dot(ps.w[arm], x)
        mean_reward = sigmoid(np.array([logit]))[0]
        confidence = ps.alpha * np.sqrt(np.sum((x**2) / ps.h[arm]))
        return float(mean_reward + confidence)

    @staticmethod
    def select(ps: GLMUCBParamState, context: Context) -> int:
        """arm selection using GLM-UCB.

        for each arm, compute sigmoid(w_a^T x) + alpha * ||x||_{H_a^{-1}}
        and return the arm with the highest upper confidence bound.
        """
        x = GLMUCBPolicy._to_vector(context)
        upper_bounds = [
            GLMUCBPolicy._arm_upper_bound(ps, arm, x) for arm in range(ps.num_arms)
        ]
        return argmax_random_tiebreak(upper_bounds)

    @classmethod
    def train(
        cls,
        ps: GLMUCBParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> GLMUCBParamState:
        """update state with observed binary reward using online Newton step.

        1. compute predicted probability p = sigmoid(w^T x)
        2. gradient = (p - y) * x + lambda * w
        3. Hessian diagonal += p * (1 - p) * x^2
        4. w -= lr * gradient / Hessian diagonal
        """
        x = cls._to_vector(context)
        y = float(reward)

        new_w = ps.w.copy()
        new_h = ps.h.copy()

        logit = np.dot(ps.w[choice], x)
        p = sigmoid(np.array([logit]))[0]

        grad = (p - y) * x + ps.lambda_ * ps.w[choice]
        new_h[choice] = ps.h[choice] + p * (1.0 - p) * (x**2)
        new_w[choice] = ps.w[choice] - ps.lr * grad / new_h[choice]

        return ps.model_copy(
            update={
                "w": new_w,
                "h": new_h,
            }
        )
