from qbrixcore.policy.base import BasePolicy
from qbrixcore.policy._reward_type import RewardType
from qbrixcore.param.spec import PolicyParam
from qbrixcore.policy.ts import (
    BetaTSPolicy,
    DiscountedTSPolicy,
    GaussianTSPolicy,
    LinTSPolicy,
    LogisticTSPolicy,
    DirichletTSPolicy,
)
from qbrixcore.policy.ucb import (
    UCB1TunedPolicy,
    KLUCBPolicy,
    KLUCBPlusPolicy,
    LinUCBPolicy,
    GLMUCBPolicy,
)
from qbrixcore.policy.eps import EpsilonPolicy
from qbrixcore.policy.moss import MOSSPolicy, MOSSAnyTimePolicy
from qbrixcore.policy.exp import EXP3Policy, EXP3IXPolicy
from qbrixcore.policy.fpl import FPLPolicy
from qbrixcore.policy.rand import RandomPolicy
from qbrixcore.policy._meta import MetaBanditPolicy
from qbrixcore.policy._meta import build_learners

POLICIES = [
    # Thompson Sampling
    BetaTSPolicy,
    DiscountedTSPolicy,
    GaussianTSPolicy,
    DirichletTSPolicy,
    LinTSPolicy,
    LogisticTSPolicy,
    # Upper Confidence Bound
    UCB1TunedPolicy,
    KLUCBPolicy,
    KLUCBPlusPolicy,
    LinUCBPolicy,
    GLMUCBPolicy,
    # Epsilon-Greedy
    EpsilonPolicy,
    # MOSS
    MOSSPolicy,
    MOSSAnyTimePolicy,
    # Adversarial
    EXP3Policy,
    EXP3IXPolicy,
    FPLPolicy,
    # Baseline
    RandomPolicy,
    # Meta
    MetaBanditPolicy,
]

__all__ = [
    "BasePolicy",
    "RewardType",
    "PolicyParam",
    # Thompson Sampling
    "BetaTSPolicy",
    "DiscountedTSPolicy",
    "GaussianTSPolicy",
    "DirichletTSPolicy",
    "LinTSPolicy",
    "LogisticTSPolicy",
    # Upper Confidence Bound
    "UCB1TunedPolicy",
    "KLUCBPolicy",
    "KLUCBPlusPolicy",
    "LinUCBPolicy",
    "GLMUCBPolicy",
    # Epsilon-Greedy
    "EpsilonPolicy",
    # MOSS
    "MOSSPolicy",
    "MOSSAnyTimePolicy",
    # Adversarial
    "EXP3Policy",
    "EXP3IXPolicy",
    "FPLPolicy",
    # Baseline
    "RandomPolicy",
    # Meta
    "MetaBanditPolicy",
    "build_learners",
    "POLICIES",
]
