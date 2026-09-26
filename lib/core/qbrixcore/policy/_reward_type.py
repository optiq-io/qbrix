from enum import Enum


class RewardType(str, Enum):
    """reward type classification for bandit policies."""

    BINARY = "binary"
    """strictly 0 or 1 rewards (bernoulli / click-through)."""

    BOUNDED = "bounded"
    """continuous rewards in the [0, 1] range."""

    CONTINUOUS = "continuous"
    """unbounded real-valued rewards."""
