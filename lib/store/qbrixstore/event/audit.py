from __future__ import annotations

from dataclasses import dataclass

from qbrixstore.event.base import Event


@dataclass
class AuditEvent(Event):
    """management operation or training-lifecycle record."""

    name: str
    tenant_id: str
    actor_id: str
    resource_type: str
    resource_id: str
    payload: dict
    timestamp_ms: int
