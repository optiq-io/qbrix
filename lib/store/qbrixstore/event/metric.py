from __future__ import annotations

from dataclasses import dataclass

from qbrixstore.event.base import Event


@dataclass
class MetricEvent(Event):
    """something that happened for a metric, and the decisions it belongs to.

    each decision is a dict of decision_id, loop_id, cycle_id, option_index and
    opened_ms. event_id is the caller's idempotency key; at_ms is when it
    happened and received_ms when qbrix heard of it.
    """

    tenant_id: str
    metric_id: str
    metric_version: str
    value: float
    decisions: list[dict]
    unit: str
    event_id: str
    at_ms: int
    received_ms: int
    source: str
