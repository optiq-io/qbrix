from __future__ import annotations

from typing import ClassVar, Union

import numpy as np
from pydantic import Field, model_validator

from qbrixcore.param.var import ArrayParam
from qbrixcore.param.var import UserConfigurable
from qbrixcore.param.state import BaseParamState
from qbrixcore.policy.base import BasePolicy
from qbrixcore.policy._reward_type import RewardType
from qbrixcore.context import Context
from qbrixcore.policy._math import sigmoid
from qbrixcore.policy._math import argmax_random_tiebreak
from qbrixcore.policy._math import unit_interval

# ---------------------------------------------------------------------------
# Beta-Bernoulli Thompson Sampling (stochastic, binary/bounded)
# ---------------------------------------------------------------------------


class BetaTSParamState(BaseParamState):
    """Parameter state for Beta-Bernoulli Thompson Sampling policy."""

    alpha_prior: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="Prior number of successes for each arm before seeing any data. "
        "Higher values make the algorithm more conservative. "
        "Common values: 1.0 (uniform prior), 2-5 (moderate optimism). "
        "Leave empty to use default of 1.0.",
    )
    beta_prior: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="Prior number of failures for each arm before seeing any data. "
        "Higher values make the algorithm more conservative. "
        "Common values: 1.0 (uniform prior), 2-5 (moderate pessimism). "
        "Leave empty to use default of 1.0.",
    )
    alpha: ArrayParam | None = None
    beta: ArrayParam | None = None
    T: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.alpha is None:
            self.alpha = np.full(self.num_arms, self.alpha_prior, dtype=np.float64)
        if self.beta is None:
            self.beta = np.full(self.num_arms, self.beta_prior, dtype=np.float64)
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        return self


class BetaTSPolicy(BasePolicy):
    """
    Beta-Bernoulli Thompson Sampling policy
     for binary rewards.

    Uses Beta distributions as conjugate priors for Bernoulli likelihoods.
    Best suited for binary rewards (0/1) or rewards that can be interpreted
    as success rates.
    """

    name: ClassVar[str] = "BetaTSPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY, RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = BetaTSParamState

    @staticmethod
    def select(ps: BetaTSParamState, context: Context) -> int:
        """Arm selection using Thompson Sampling."""
        samples = np.random.beta(ps.alpha, ps.beta, size=ps.num_arms)
        return int(np.argmax(samples))

    @classmethod
    def train(
        cls,
        ps: BetaTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> BetaTSParamState:
        """
        Update state with observed reward using Beta-Bernoulli conjugacy.

        Converts reward to binary: 1 if reward > 0.5, else 0.
        """
        new_alpha = ps.alpha.copy()
        new_beta = ps.beta.copy()
        new_T = ps.T.copy()

        # convert reward to binary
        if reward not in [0, 1]:
            binary_reward = 1 if reward > 0.5 else 0
        else:
            binary_reward = int(reward)

        new_T[choice] += 1
        if binary_reward == 1:
            new_alpha[choice] += 1
        else:
            new_beta[choice] += 1

        return ps.model_copy(
            update={
                "alpha": new_alpha,
                "beta": new_beta,
                "T": new_T,
            }
        )


# ---------------------------------------------------------------------------
# Discounted Thompson Sampling (stochastic, binary/bounded, non-stationary)
# ---------------------------------------------------------------------------


class DiscountedTSParamState(BaseParamState):
    """Parameter state for Discounted Thompson Sampling policy."""

    alpha_prior: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="Prior number of successes for each arm before seeing any data. "
        "Higher values make the algorithm more conservative. "
        "Common values: 1.0 (uniform prior), 2-5 (moderate optimism). "
        "Leave empty to use default of 1.0.",
    )
    beta_prior: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="Prior number of failures for each arm before seeing any data. "
        "Higher values make the algorithm more conservative. "
        "Common values: 1.0 (uniform prior), 2-5 (moderate pessimism). "
        "Leave empty to use default of 1.0.",
    )
    gamma: UserConfigurable[float] = Field(
        ...,
        gt=0.0,
        lt=1.0,
        description="Discount factor controlling how quickly old observations fade. "
        "Values close to 1.0 (e.g. 0.999) forget slowly — good for gradual drift. "
        "Lower values (e.g. 0.95-0.99) forget faster — good for rapid changes. "
        "The effective memory window is approximately 1/(1-gamma) observations. "
        "gamma=0.99 → ~100 obs window, gamma=0.999 → ~1000 obs window. "
        "Must be between 0 and 1 (exclusive).",
    )
    alpha: ArrayParam | None = None
    beta: ArrayParam | None = None
    T: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.alpha is None:
            self.alpha = np.full(self.num_arms, self.alpha_prior, dtype=np.float64)
        if self.beta is None:
            self.beta = np.full(self.num_arms, self.beta_prior, dtype=np.float64)
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        return self


class DiscountedTSPolicy(BasePolicy):
    """
    Discounted Thompson Sampling policy for non-stationary environments.

    Extends Beta-Bernoulli Thompson Sampling with a geometric discount factor
    that exponentially decays old observations. This allows the algorithm to
    adapt to changing reward distributions without requiring explicit change
    detection.

    On each update, all alpha and beta counts are multiplied by gamma before
    incorporating the new observation. The effective sample size is bounded
    by approximately 1/(1-gamma), so the algorithm maintains a sliding window
    of influence without a hard cutoff.
    """

    name: ClassVar[str] = "DiscountedTSPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY, RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = DiscountedTSParamState

    @staticmethod
    def select(ps: DiscountedTSParamState, context: Context) -> int:
        """Arm selection using Thompson Sampling."""
        samples = np.random.beta(ps.alpha, ps.beta, size=ps.num_arms)
        return int(np.argmax(samples))

    @classmethod
    def train(
        cls,
        ps: DiscountedTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> DiscountedTSParamState:
        """
        Update state with geometric discounting.

        1. Discount all alpha/beta counts by gamma (fade old observations)
        2. Update chosen arm with new observation
        """
        # discount all arms
        new_alpha = ps.gamma * ps.alpha
        new_beta = ps.gamma * ps.beta
        new_T = ps.T.copy()

        # convert reward to binary
        if reward not in [0, 1]:
            binary_reward = 1 if reward > 0.5 else 0
        else:
            binary_reward = int(reward)

        new_T[choice] += 1
        if binary_reward == 1:
            new_alpha[choice] += 1
        else:
            new_beta[choice] += 1

        return ps.model_copy(
            update={
                "alpha": new_alpha,
                "beta": new_beta,
                "T": new_T,
            }
        )


# ---------------------------------------------------------------------------
# Bounded Beta Thompson Sampling (stochastic, bounded on a declared range)
# ---------------------------------------------------------------------------


class BoundedBetaTSParamState(BaseParamState):
    """Parameter state for Bounded Beta Thompson Sampling.

    The range [lo, hi] is construction input from the metric that declares
    it, not a user setting.
    """

    lo: float = 0.0
    hi: float = 1.0
    alpha: ArrayParam | None = None
    beta: ArrayParam | None = None
    T: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.lo >= self.hi:
            raise ValueError(f"lo must be below hi, got [{self.lo}, {self.hi}]")
        if self.alpha is None:
            self.alpha = np.full(
                self.num_arms, BoundedBetaTSPolicy.PRIOR, dtype=np.float64
            )
        if self.beta is None:
            self.beta = np.full(
                self.num_arms, BoundedBetaTSPolicy.PRIOR, dtype=np.float64
            )
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        return self


class BoundedBetaTSPolicy(BasePolicy):
    """
    Beta Thompson Sampling on a declared range that learns from the whole value.

    Each outcome is rescaled from [lo, hi] onto [0, 1] and clamped there, then
    added fractionally: alpha grows by the rescaled value and beta by its
    complement, so a 0.9 teaches more than a 0.51. Each arm's posterior is
    over the mean of the rescaled outcome. Ties are broken at random.

    Every outcome counts as one Bernoulli trial's worth of evidence, so on
    tightly spread outcomes the posterior is wider than the data warrants
    and the policy explores longer than it needs to.
    """

    name: ClassVar[str] = "BoundedBetaTSPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY, RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = BoundedBetaTSParamState

    PRIOR: ClassVar[float] = 1.0

    @staticmethod
    def select(ps: BoundedBetaTSParamState, context: Context) -> int:
        """Arm selection using Thompson Sampling."""
        return argmax_random_tiebreak(np.random.beta(ps.alpha, ps.beta))

    @classmethod
    def train(
        cls,
        ps: BoundedBetaTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> BoundedBetaTSParamState:
        """Add the rescaled, clamped outcome to alpha and its complement to beta."""
        y = unit_interval(reward, ps.lo, ps.hi)
        new_alpha = ps.alpha.copy()
        new_beta = ps.beta.copy()
        new_T = ps.T.copy()

        new_T[choice] += 1
        new_alpha[choice] += y
        new_beta[choice] += 1.0 - y

        return ps.model_copy(
            update={
                "alpha": new_alpha,
                "beta": new_beta,
                "T": new_T,
            }
        )


# ---------------------------------------------------------------------------
# Gaussian Thompson Sampling (stochastic, continuous)
# ---------------------------------------------------------------------------


class GaussianTSParamState(BaseParamState):
    """Parameter state for Gaussian Thompson Sampling policy."""

    prior_mean: UserConfigurable[float] = Field(
        default=0.0,
        description="Initial expected reward for all arms before seeing data. "
        "Should reflect your prior belief about average rewards. "
        "For click-through rates, use 0.01-0.05. "
        "For conversion rates, use 0.1-0.3. "
        "Leave empty to use default of 0.0.",
    )
    prior_precision: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="Prior certainty about the mean (inverse of variance). "
        "Higher values (10-100) indicate strong prior belief, lower values (0.1-1.0) allow more "
        "learning from data. Leave empty to use default of 1.0.",
    )
    noise_precision: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="Precision (inverse variance) of reward observations. "
        "Lower values for noisy environments (0.1-0.5), higher for stable rewards (5-10). "
        "This controls how much each observation affects beliefs. "
        "Leave empty to use default of 1.0.",
    )
    posterior_mean: ArrayParam | None = None
    posterior_precision: ArrayParam | None = None
    T: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.posterior_mean is None:
            self.posterior_mean = np.full(
                self.num_arms, self.prior_mean, dtype=np.float64
            )
        if self.posterior_precision is None:
            self.posterior_precision = np.full(
                self.num_arms, self.prior_precision, dtype=np.float64
            )
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        return self


class GaussianTSPolicy(BasePolicy):
    """
    Gaussian Thompson Sampling policy for continuous rewards.

    Uses Gaussian distributions with conjugate Gaussian priors.
    Assumes rewards are normally distributed and updates both mean and precision.
    """

    name: ClassVar[str] = "GaussianTSPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [RewardType.CONTINUOUS]
    param_state_cls: type[BaseParamState] = GaussianTSParamState

    @staticmethod
    def select(ps: GaussianTSParamState, context: Context) -> int:
        """Arm selection using Gaussian Thompson Sampling."""
        samples = [
            np.random.normal(
                ps.posterior_mean[i], 1.0 / np.sqrt(ps.posterior_precision[i])
            )
            for i in range(ps.num_arms)
        ]
        return int(np.argmax(samples))

    @classmethod
    def train(
        cls,
        ps: GaussianTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> GaussianTSParamState:
        """Update state with observed reward using Gaussian-Gaussian conjugacy."""
        new_posterior_mean = ps.posterior_mean.copy()
        new_posterior_precision = ps.posterior_precision.copy()
        new_T = ps.T.copy()

        new_T[choice] += 1

        prev_precision = ps.posterior_precision[choice]
        prev_mean = ps.posterior_mean[choice]

        new_posterior_precision[choice] = prev_precision + ps.noise_precision
        new_posterior_mean[choice] = (
            prev_precision * prev_mean + ps.noise_precision * reward
        ) / new_posterior_precision[choice]

        return ps.model_copy(
            update={
                "posterior_mean": new_posterior_mean,
                "posterior_precision": new_posterior_precision,
                "T": new_T,
            }
        )


# ---------------------------------------------------------------------------
# Normal-Inverse-Gamma Gaussian Thompson Sampling (stochastic, continuous)
# ---------------------------------------------------------------------------


class GaussianNIGTSParamState(BaseParamState):
    """Parameter state for Normal-Inverse-Gamma Gaussian Thompson Sampling.

    Per arm: outcome count, running mean and sum of squared deviations
    (Welford), which together are sufficient for an unknown mean and variance.
    """

    T: ArrayParam | None = None
    mean: ArrayParam | None = None
    m2: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        if self.mean is None:
            self.mean = np.zeros(self.num_arms, dtype=np.float64)
        if self.m2 is None:
            self.m2 = np.zeros(self.num_arms, dtype=np.float64)
        return self


class GaussianNIGTSPolicy(BasePolicy):
    """
    Gaussian Thompson Sampling that learns the spread of outcomes from the data.

    Each arm has a Normal-Inverse-Gamma posterior over its mean and variance.
    Selection samples a variance, then a mean given it (a Student-t draw), and
    picks the highest sample, breaking ties at random.

    Nothing about the outcome scale is assumed: an arm with fewer than
    MIN_OUTCOMES outcomes is maximally uncertain and is tried first, and the
    variance prior is worth PRIOR_SHAPE * 2 outcomes at the pooled within-arm
    variance, so euros, minutes and unit-scale values all work unscaled.
    """

    name: ClassVar[str] = "GaussianNIGTSPolicy"
    category: ClassVar[str] = "stochastic"
    reward_types: ClassVar[list[RewardType]] = [RewardType.CONTINUOUS]
    param_state_cls: type[BaseParamState] = GaussianNIGTSParamState

    MIN_OUTCOMES: ClassVar[int] = 2
    PRIOR_SHAPE: ClassVar[float] = 1.0

    @classmethod
    def _pooled_variance(cls, ps: GaussianNIGTSParamState) -> float:
        warm = ps.T >= cls.MIN_OUTCOMES
        dof = np.sum(ps.T[warm] - 1)
        if dof <= 0:
            return 0.0
        return float(np.sum(ps.m2[warm]) / dof)

    @classmethod
    def _sample_means(cls, ps: GaussianNIGTSParamState) -> np.ndarray:
        """one posterior draw of each arm's mean; +inf for arms still cold."""
        samples = np.full(ps.num_arms, np.inf, dtype=np.float64)
        warm = ps.T >= cls.MIN_OUTCOMES
        if not np.any(warm):
            return samples

        n = ps.T[warm].astype(np.float64)
        shape = cls.PRIOR_SHAPE + (n - 1.0) / 2.0
        scale = cls.PRIOR_SHAPE * cls._pooled_variance(ps) + ps.m2[warm] / 2.0
        variance = scale / np.random.gamma(shape)
        samples[warm] = np.random.normal(ps.mean[warm], np.sqrt(variance / n))
        return samples

    @classmethod
    def select(cls, ps: GaussianNIGTSParamState, context: Context) -> int:
        """Arm selection using Normal-Inverse-Gamma Thompson Sampling."""
        return argmax_random_tiebreak(cls._sample_means(ps))

    @classmethod
    def train(
        cls,
        ps: GaussianNIGTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> GaussianNIGTSParamState:
        """Update the chosen arm's count, mean and M2 with Welford's method."""
        y = float(reward)
        new_T = ps.T.copy()
        new_mean = ps.mean.copy()
        new_m2 = ps.m2.copy()

        new_T[choice] += 1
        delta = y - ps.mean[choice]
        new_mean[choice] = ps.mean[choice] + delta / new_T[choice]
        new_m2[choice] = ps.m2[choice] + delta * (y - new_mean[choice])

        return ps.model_copy(
            update={
                "T": new_T,
                "mean": new_mean,
                "m2": new_m2,
            }
        )


# ---------------------------------------------------------------------------
# Linear Thompson Sampling (contextual, all reward types)
# ---------------------------------------------------------------------------


class LinTSParamState(BaseParamState):
    """Parameter state for Linear Thompson Sampling policy."""

    dim: UserConfigurable[int] = Field(
        ...,
        gt=0,
        description="Dimension of the context vector. "
        "This must match the length of context features you provide during selection. "
        "For example, use 5 if you pass [user_age, user_location, time_of_day, device_type, page_views] as context. "
        "Must be a positive integer.",
    )
    v: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="Scale parameter controlling exploration vs exploitation. "
        "Higher values (2-5) increase exploration, lower values (0.5-1) focus more on exploitation. "
        "Start with 1.0 and increase if the algorithm seems too conservative. "
        "Leave empty to use default of 1.0.",
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


class LinTSPolicy(BasePolicy):
    """
    Linear Thompson Sampling policy for contextual multi-armed bandit.

    Uses Bayesian linear regression with Gaussian priors to model the
    reward function and samples from the posterior to select arms.
    """

    name: ClassVar[str] = "LinTSPolicy"
    category: ClassVar[str] = "contextual"
    reward_types: ClassVar[list[RewardType]] = [
        RewardType.BINARY,
        RewardType.BOUNDED,
        RewardType.CONTINUOUS,
    ]
    param_state_cls: type[BaseParamState] = LinTSParamState

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
    def _sample_theta(ps: LinTSParamState, arm: int) -> np.ndarray:
        """Sample parameter vector from posterior distribution for an arm."""
        try:
            b_inv = np.linalg.inv(ps.d[arm])
            mu = np.dot(b_inv, ps.r[arm]).flatten()
            cov = (ps.v**2) * b_inv
            cov = (cov + cov.T) / 2
            theta_sample = np.random.multivariate_normal(mu, cov)
            return theta_sample.reshape(-1, 1)
        except np.linalg.LinAlgError:
            try:
                b_inv = np.linalg.pinv(ps.d[arm])
                mu = np.dot(b_inv, ps.r[arm])
                return mu
            except Exception:  # noqa
                return np.zeros((ps.dim, 1), dtype=np.float64)

    @staticmethod
    def select(ps: LinTSParamState, context: Context) -> int:
        """Arm selection using Linear Thompson Sampling."""
        x = LinTSPolicy._reshape_context_vector(context)
        pred = []
        for arm in range(ps.num_arms):
            theta_sample = LinTSPolicy._sample_theta(ps, arm)
            expected_reward = np.dot(theta_sample.T, x).item()
            pred.append(expected_reward)
        return int(np.argmax(pred))

    @classmethod
    def train(
        cls,
        ps: LinTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> LinTSParamState:
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
# Normal-Inverse-Gamma Linear Thompson Sampling (contextual, continuous)
# ---------------------------------------------------------------------------


class LinNIGTSParamState(BaseParamState):
    """Parameter state for Normal-Inverse-Gamma Linear Thompson Sampling.

    Per arm: the posterior precision matrix, the outcome-weighted context sum,
    and the count, sum and sum of squares of outcomes. dim is derived from the
    experiment's context schema, never chosen by a person.
    """

    dim: int = Field(..., gt=0)
    precision: ArrayParam | None = None  # (num_arms, dim, dim)
    b: ArrayParam | None = None  # (num_arms, dim)
    y_sum: ArrayParam | None = None
    y_sq_sum: ArrayParam | None = None
    T: ArrayParam | None = None

    @model_validator(mode="after")
    def set_defaults(self):
        if self.precision is None:
            self.precision = np.array(
                [
                    LinNIGTSPolicy.RIDGE * np.identity(self.dim, dtype=np.float64)
                    for _ in range(self.num_arms)
                ]
            )
        if self.b is None:
            self.b = np.zeros((self.num_arms, self.dim), dtype=np.float64)
        if self.y_sum is None:
            self.y_sum = np.zeros(self.num_arms, dtype=np.float64)
        if self.y_sq_sum is None:
            self.y_sq_sum = np.zeros(self.num_arms, dtype=np.float64)
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        return self


class LinNIGTSPolicy(BasePolicy):
    """
    Linear Thompson Sampling that learns the spread of outcomes from the data.

    Each arm is a Bayesian linear regression with a Normal-Inverse-Gamma
    posterior: weights theta ~ N(mu, sigma^2 * precision^-1), with the noise
    variance sigma^2 learned from the residuals rather than fixed. Selection
    samples sigma^2, then theta, and picks the highest theta^T x, breaking ties
    at random.

    As in GaussianNIGTSPolicy, arms with fewer than MIN_OUTCOMES outcomes are
    tried first, and the noise prior sits at the pooled within-arm outcome
    variance, so the outcome scale never needs rescaling.
    """

    name: ClassVar[str] = "LinNIGTSPolicy"
    category: ClassVar[str] = "contextual"
    reward_types: ClassVar[list[RewardType]] = [RewardType.CONTINUOUS]
    param_state_cls: type[BaseParamState] = LinNIGTSParamState

    MIN_OUTCOMES: ClassVar[int] = 2
    PRIOR_SHAPE: ClassVar[float] = 1.0
    RIDGE: ClassVar[float] = 1.0

    @staticmethod
    def _to_vector(context: Context) -> np.ndarray:
        v = context.vector
        if isinstance(v, list):
            v = np.array(v, dtype=np.float64)
        return v.ravel()

    @classmethod
    def _pooled_variance(cls, ps: LinNIGTSParamState) -> float:
        warm = ps.T >= cls.MIN_OUTCOMES
        dof = np.sum(ps.T[warm] - 1)
        if dof <= 0:
            return 0.0
        m2 = ps.y_sq_sum[warm] - ps.y_sum[warm] ** 2 / ps.T[warm]
        return float(max(np.sum(m2), 0.0) / dof)

    @classmethod
    def _noise_posterior(
        cls, ps: LinNIGTSParamState, arm: int, mu: np.ndarray
    ) -> tuple[float, float]:
        """inverse-gamma (shape, scale) of an arm's noise variance."""
        shape = cls.PRIOR_SHAPE + ps.T[arm] / 2.0
        explained = float(mu @ ps.precision[arm] @ mu)
        residual = max(float(ps.y_sq_sum[arm]) - explained, 0.0)
        scale = cls.PRIOR_SHAPE * cls._pooled_variance(ps) + residual / 2.0
        return shape, scale

    @classmethod
    def _sample_theta(cls, ps: LinNIGTSParamState, arm: int) -> np.ndarray:
        try:
            chol = np.linalg.cholesky(ps.precision[arm])
            mu = np.linalg.solve(ps.precision[arm], ps.b[arm])
        except np.linalg.LinAlgError:
            return np.linalg.pinv(ps.precision[arm]) @ ps.b[arm]

        shape, scale = cls._noise_posterior(ps, arm, mu)
        variance = scale / np.random.gamma(shape)
        z = np.random.standard_normal(ps.dim)
        return mu + np.sqrt(variance) * np.linalg.solve(chol.T, z)

    @classmethod
    def select(cls, ps: LinNIGTSParamState, context: Context) -> int:
        """Arm selection using Normal-Inverse-Gamma Linear Thompson Sampling."""
        x = cls._to_vector(context)
        scores = np.full(ps.num_arms, np.inf, dtype=np.float64)
        for arm in range(ps.num_arms):
            if ps.T[arm] >= cls.MIN_OUTCOMES:
                scores[arm] = float(cls._sample_theta(ps, arm) @ x)
        return argmax_random_tiebreak(scores)

    @classmethod
    def train(
        cls,
        ps: LinNIGTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> LinNIGTSParamState:
        """Update the chosen arm's sufficient statistics."""
        x = cls._to_vector(context)
        y = float(reward)

        new_precision = ps.precision.copy()
        new_b = ps.b.copy()
        new_y_sum = ps.y_sum.copy()
        new_y_sq_sum = ps.y_sq_sum.copy()
        new_T = ps.T.copy()

        new_precision[choice] = ps.precision[choice] + np.outer(x, x)
        new_b[choice] = ps.b[choice] + y * x
        new_y_sum[choice] += y
        new_y_sq_sum[choice] += y * y
        new_T[choice] += 1

        return ps.model_copy(
            update={
                "precision": new_precision,
                "b": new_b,
                "y_sum": new_y_sum,
                "y_sq_sum": new_y_sq_sum,
                "T": new_T,
            }
        )


# ---------------------------------------------------------------------------
# Bounded Normal-Inverse-Gamma Linear Thompson Sampling (contextual, bounded)
# ---------------------------------------------------------------------------


class BoundedLinNIGTSParamState(LinNIGTSParamState):
    """Parameter state for Bounded Normal-Inverse-Gamma Linear Thompson Sampling.

    The range [lo, hi] is construction input from the metric that declares
    it, not a user setting.
    """

    lo: float = 0.0
    hi: float = 1.0

    @model_validator(mode="after")
    def check_range(self):
        if self.lo >= self.hi:
            raise ValueError(f"lo must be below hi, got [{self.lo}, {self.hi}]")
        return self


class BoundedLinNIGTSPolicy(LinNIGTSPolicy):
    """
    LinNIGTSPolicy on a declared range.

    Each outcome is rescaled from [lo, hi] onto [0, 1] and clamped there
    before it is learned, so a score is modelled on the same scale whatever
    range its metric declares.
    """

    name: ClassVar[str] = "BoundedLinNIGTSPolicy"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY, RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = BoundedLinNIGTSParamState

    @classmethod
    def train(
        cls,
        ps: BoundedLinNIGTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> BoundedLinNIGTSParamState:
        """Learn the rescaled, clamped outcome."""
        return super().train(ps, context, choice, unit_interval(reward, ps.lo, ps.hi))


# ---------------------------------------------------------------------------
# Logistic Thompson Sampling (contextual, binary)
# ---------------------------------------------------------------------------


class LogisticTSParamState(BaseParamState):
    """Parameter state for Logistic Thompson Sampling policy.

    Maintains per-arm weight vectors and Hessian approximations
    for Laplace-approximated posterior sampling.
    """

    dim: UserConfigurable[int] = Field(
        ...,
        gt=0,
        description="Dimension of the context vector. "
        "This must match the length of context features you provide during selection. "
        "For example, use 5 if you pass [user_age, user_location, time_of_day, device_type, page_views] as context. "
        "Must be a positive integer.",
    )
    lambda_: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="L2 regularization strength. "
        "Higher values (2-5) prevent overfitting with sparse data, "
        "lower values (0.1-0.5) allow the model to fit more closely. "
        "Start with 1.0. Increase if you have few observations per arm. "
        "Leave empty to use default of 1.0.",
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


class LogisticTSPolicy(BasePolicy):
    """
    Logistic Thompson Sampling policy for contextual bandits with binary rewards.

    Uses Laplace approximation to maintain a Gaussian posterior over per-arm
    logistic regression weights. At selection time, samples from the posterior
    and picks the arm with the highest predicted P(reward=1|context).

    Training performs an online Newton step on the logistic loss with L2
    regularization, using a diagonal Hessian approximation for efficiency.

    This is the most widely deployed contextual bandit policy for binary
    rewards in production systems (ads, recommendations, personalization).
    """

    name: ClassVar[str] = "LogisticTSPolicy"
    category: ClassVar[str] = "contextual"
    reward_types: ClassVar[list[RewardType]] = [RewardType.BINARY]
    param_state_cls: type[BaseParamState] = LogisticTSParamState

    @staticmethod
    def _to_vector(context: Context) -> np.ndarray:
        """extract context as 1d numpy array."""
        v = context.vector
        if isinstance(v, list):
            v = np.array(v, dtype=np.float64)
        return v.ravel()

    @staticmethod
    def select(ps: LogisticTSParamState, context: Context) -> int:
        """arm selection using Logistic Thompson Sampling.

        for each arm, sample weights from the Laplace posterior
        N(w_a, diag(1/h_a)) and compute sigmoid(w_a^T x).
        return the arm with the highest sampled probability.
        """
        x = LogisticTSPolicy._to_vector(context)
        best_arm = 0
        best_score = -np.inf

        for arm in range(ps.num_arms):
            std = 1.0 / np.sqrt(ps.h[arm])
            w_sample = np.random.normal(ps.w[arm], std)
            logit = np.dot(w_sample, x)
            score = sigmoid(np.array([logit]))[0]

            if score > best_score:
                best_score = score
                best_arm = arm

        return int(best_arm)

    @classmethod
    def train(
        cls,
        ps: LogisticTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> LogisticTSParamState:
        """
        update state with observed binary reward using online Newton step.

        performs a single step of online logistic regression:
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


# ---------------------------------------------------------------------------
# Dirichlet-Categorical Thompson Sampling (stochastic, bounded)
# ---------------------------------------------------------------------------


class DirichletTSParamState(BaseParamState):
    """Parameter state for Dirichlet-Categorical Thompson Sampling policy.

    Each arm maintains a Dirichlet posterior over a shared set of discrete
    outcomes (0, 1, ..., num_outcomes-1). The prior is symmetric Dirichlet
    with concentration `concentration_prior` on each outcome bucket.

    State layout:
        alpha: shape (num_arms, num_outcomes) — per-arm Dirichlet concentration
               vectors. alpha[a, k] = concentration_prior + count(arm=a, outcome=k).
        T:     shape (num_arms,) — per-arm pull counts.
    """

    k: UserConfigurable[int] = Field(
        ...,
        gt=1,
        description="Number of discrete outcome categories (K). "
        "Reward observations must be integer indices in [0, K-1]. "
        "Examples: 3 for low/medium/high ratings, 5 for star ratings. "
        "Must be an integer greater than 1.",
    )
    concentration_prior: UserConfigurable[float] = Field(
        default=1.0,
        gt=0.0,
        description="Symmetric Dirichlet prior concentration for each outcome bucket. "
        "1.0 gives a uniform (non-informative) prior. "
        "Values < 1.0 (e.g. 0.5) yield a sparse prior that concentrates mass "
        "on fewer outcomes. Values > 1.0 pull posteriors toward uniform. "
        "Leave empty to use default of 1.0.",
    )
    alpha: ArrayParam | None = None  # shape (num_arms, k)
    T: ArrayParam | None = None  # shape (num_arms,)

    @model_validator(mode="after")
    def set_defaults(self):
        if self.alpha is None:
            self.alpha = np.full(
                (self.num_arms, self.k),
                self.concentration_prior,
                dtype=np.float64,
            )
        if self.T is None:
            self.T = np.zeros(self.num_arms, dtype=np.int64)
        return self


class DirichletTSPolicy(BasePolicy):
    """
    Dirichlet-Categorical Thompson Sampling policy for discrete-outcome rewards.

    Uses Dirichlet distributions as conjugate priors for Categorical likelihoods.
    Each arm maintains a Dirichlet posterior over K discrete outcome buckets.

    At selection time, one sample is drawn from each arm's Dirichlet posterior.
    The sampled vector is a probability simplex over outcomes; the arm's score is
    the expected reward under that sample: sum(outcome_values * p_sample).

    At training time, the observed outcome index increments the corresponding
    concentration bucket — a single sufficient-statistic update, exact conjugacy.

    When to use:
    - Rewards are inherently categorical (ratings, engagement tiers, grades)
    - You want to model the full outcome distribution, not just its mean
    - Beta-TS is too coarse (collapses multi-outcome structure to binary)

    outcome_values controls the reward weighting. With default unit spacing
    (0, 1, ..., K-1), higher outcome indices are linearly more valuable.
    Custom values let you express non-linear utility (e.g. [0, 0, 1, 5, 20]
    for a heavy-tail distribution where top ratings matter most).
    """

    name: ClassVar[str] = "DirichletTSPolicy"
    category: ClassVar[str] = "stochastic"
    # bounded: reward indices are integers in [0, K-1], a bounded discrete space
    reward_types: ClassVar[list[RewardType]] = [RewardType.BOUNDED]
    param_state_cls: type[BaseParamState] = DirichletTSParamState

    @staticmethod
    def _outcome_values(k: int) -> np.ndarray:
        """default outcome values: unit-spaced integers 0..K-1."""
        return np.arange(k, dtype=np.float64)

    @staticmethod
    def select(ps: DirichletTSParamState, context: Context) -> int:
        """arm selection via Dirichlet-Categorical Thompson Sampling.

        draws a Dirichlet sample for each arm, computes expected reward under
        that sample using default unit-spaced outcome values, returns argmax.
        """
        values = DirichletTSPolicy._outcome_values(ps.k)
        scores = np.empty(ps.num_arms, dtype=np.float64)
        for arm in range(ps.num_arms):
            p_sample = np.random.dirichlet(ps.alpha[arm])
            scores[arm] = np.dot(p_sample, values)
        return int(np.argmax(scores))

    @classmethod
    def train(
        cls,
        ps: DirichletTSParamState,
        context: Context,
        choice: int,
        reward: Union[int, float, np.float64],
    ) -> DirichletTSParamState:
        """update Dirichlet posterior for the chosen arm.

        reward is interpreted as the observed outcome index (0..num_outcomes-1).
        non-integer rewards are rounded to the nearest integer and clipped to
        the valid range, so callers that pass continuous rewards still work
        (though using DirichletTS with continuous rewards is semantically odd).
        """
        outcome = int(np.clip(round(float(reward)), 0, ps.k - 1))

        new_alpha = ps.alpha.copy()
        new_T = ps.T.copy()

        new_alpha[choice, outcome] += 1.0
        new_T[choice] += 1

        return ps.model_copy(
            update={
                "alpha": new_alpha,
                "T": new_T,
            }
        )
