from __future__ import annotations

from typing import Any
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from proxysvc.mod.gate.model.rule import OperatorType
from proxysvc.util import _parse_datetime


class RuleRequest(BaseModel):
    key: str = Field(..., min_length=1)
    operator: OperatorType
    value: Any
    arm_id: Optional[str] = None
    arm_name: Optional[str] = None


class GateConfigRequest(BaseModel):
    enabled: bool = True
    rollout_percentage: float = 100.0
    default_arm_id: Optional[str] = None
    schedule_start: Optional[str] = None
    schedule_end: Optional[str] = None
    active_hours_start: Optional[str] = None
    active_hours_end: Optional[str] = None
    timezone: str = "UTC"
    rules: List[RuleRequest] = []

    @model_validator(mode="after")
    def _validate_schedule_range(self) -> "GateConfigRequest":
        if self.schedule_start and self.schedule_end:
            start = _parse_datetime(self.schedule_start)
            end = _parse_datetime(self.schedule_end)
            if start and end and start >= end:
                raise ValueError("schedule_start must be before schedule_end")
        return self


class GateConfigPatchRequest(BaseModel):
    """a partial gate update.

    a field absent from the request body is left as stored; an explicit null
    clears it. `rules` is replace-in-whole — omit to keep the stored rules, send
    `[]` to remove them.
    """

    enabled: Optional[bool] = None
    rollout_percentage: Optional[float] = None
    default_arm_id: Optional[str] = None
    schedule_start: Optional[str] = None
    schedule_end: Optional[str] = None
    active_hours_start: Optional[str] = None
    active_hours_end: Optional[str] = None
    timezone: Optional[str] = None
    rules: Optional[List[RuleRequest]] = None

    @model_validator(mode="after")
    def _reject_null_on_non_nullable(self) -> "GateConfigPatchRequest":
        for name in ("enabled", "rollout_percentage", "timezone", "rules"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    @model_validator(mode="after")
    def _validate_schedule_range(self) -> "GateConfigPatchRequest":
        if self.schedule_start and self.schedule_end:
            start = _parse_datetime(self.schedule_start)
            end = _parse_datetime(self.schedule_end)
            if start and end and start >= end:
                raise ValueError("schedule_start must be before schedule_end")
        return self

    def changes(self) -> dict[str, Any]:
        """the supplied fields only, keyed by column name."""
        out: dict[str, Any] = {}
        for name in self.model_fields_set:
            value = getattr(self, name)
            out[name] = [r.model_dump() for r in value] if name == "rules" else value
        return out


class GateEvaluateRequest(BaseModel):
    """a sample context to run the gate against, without touching live traffic."""

    context_id: str = Field(
        default="",
        description="identifier the rollout hashes on; blank is evaluated as-is",
    )
    context_metadata: dict = Field(
        default_factory=dict, description="attributes the targeting rules read"
    )
