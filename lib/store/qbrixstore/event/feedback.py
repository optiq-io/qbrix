from __future__ import annotations

from dataclasses import dataclass

from qbrixstore.event.base import Event


@dataclass
class FeedbackEvent(Event):
    """reward reported for a prior selection; the learning-path signal."""

    tenant_id: str
    experiment_id: str
    request_id: str
    arm_index: int
    reward: float
    context_id: str
    context_vector: list[float]
    context_metadata: dict
    timestamp_ms: int
