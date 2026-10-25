from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import field

from qbrixstore.event.base import Event


@dataclass
class SelectionEvent(Event):
    """event emitted when an arm is selected for a context.

    event_id is unique per emission and is the dedup key for billing-grade
    ground truth. request_id is the deterministic selection token (no nonce)
    and is the wrong identity level for metering.
    """

    tenant_id: str
    experiment_id: str
    request_id: str
    # kw_only so it keeps its place in the schema while carrying a default;
    # the default is what lets entries published before event_id existed still
    # decode, each getting a distinct id rather than colliding on a constant.
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()), kw_only=True)
    arm_id: str
    arm_name: str
    arm_index: int
    is_default: bool
    context_id: str
    context_vector: list[float]
    context_metadata: dict
    timestamp_ms: int
    policy: str
    loop_id: str = ""
    cycle_id: str = ""
    decision_id: str = ""
    reason: str = ""
    unit: str = ""
    properties: dict = field(default_factory=dict)
    metric_id: str = ""
    metric_version: str = ""
    metric_type: str = ""
    score_lo: float = 0.0
    score_hi: float = 0.0
    window_ms: int = 0
