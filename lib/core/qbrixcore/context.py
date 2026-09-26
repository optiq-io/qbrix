import uuid
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Context:
    """Request context for bandit selection.

    The vector field accepts both list[float] and np.ndarray. Contextual policies
    (e.g. LinUCB, LinTS) will convert lists to arrays internally when needed.
    Stochastic policies ignore the vector entirely.

    If the experiment sits behind a feature-gate rollout, id should be a stable
    identifier for the visitor/session (not a fresh one per request) — proxysvc
    buckets rollout membership by hashing it. The uuid4 default below is only a
    safe fallback for callers that don't need that stability.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    vector: np.ndarray | list[float] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
