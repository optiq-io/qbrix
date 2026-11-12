from __future__ import annotations

import re
from datetime import date
from datetime import datetime
from datetime import time
from typing import Annotated
from typing import Any
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import PrivateAttr
from pydantic import model_validator

from proxysvc.core.targeting import Operator
from proxysvc.core.targeting import bucket
from proxysvc.core.targeting import holds

MAX_CONDITIONS = 20
MAX_LIST_VALUES = 100

_LISTS = frozenset({"in", "not_in"})
_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

Scalar = str | int | float | bool


class Condition(BaseModel):
    """one condition of an audience: a request holds it when its context has
    the property and the property stands in the operator's relation to the
    value. a request without the property never holds it, whatever the
    operator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    property: Annotated[str, Field(min_length=1, max_length=64)]
    operator: Operator
    value: Scalar | list[Scalar]

    @model_validator(mode="after")
    def _value_fits(self) -> Condition:
        listed = isinstance(self.value, list)
        if self.operator in _LISTS and not listed:
            raise ValueError(
                f"{self.property} {self.operator} takes a list of values, "
                f'like ["NL", "BE"]'
            )
        if self.operator not in _LISTS and listed:
            raise ValueError(
                f"{self.property} {self.operator} takes one value; "
                f"use in or not_in for a list"
            )
        if listed and not 0 < len(self.value) <= MAX_LIST_VALUES:
            raise ValueError(
                f"{self.property} {self.operator} takes 1 to {MAX_LIST_VALUES} values"
            )
        return self

    def holds(self, properties: dict) -> bool:
        if self.property not in properties:
            return False
        return holds(self.operator, properties[self.property], self.value)


class Hours(BaseModel):
    """daily hours, from start until end: 09:00 to 18:00 decides from nine
    and stops at six. a start after the end runs past midnight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: str
    end: str

    _start: time = PrivateAttr()
    _end: time = PrivateAttr()

    @model_validator(mode="after")
    def _clock(self) -> Hours:
        for name in ("start", "end"):
            if not _CLOCK.match(getattr(self, name)):
                raise ValueError(
                    f'hours.{name} is a time like "09:00", got {getattr(self, name)!r}'
                )
        if self.start == self.end:
            raise ValueError(
                "hours start and end are the same; leave hours out to decide all day"
            )
        self._start = time.fromisoformat(self.start)
        self._end = time.fromisoformat(self.end)
        return self

    def open(self, at: time) -> bool:
        if self._start < self._end:
            return self._start <= at < self._end
        return at >= self._start or at < self._end


class Schedule(BaseModel):
    """when a loop decides: daily hours and a date it starts on, both read in
    the schedule's timezone. no end date: a loop is paused or retired, never
    ended by its schedule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hours: Hours | None = None
    starts_on: date | None = None
    timezone: str | None = None

    _zone: ZoneInfo | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _zoned(self) -> Schedule:
        if self.timezone is None:
            if self.hours is not None or self.starts_on is not None:
                raise ValueError(
                    "a schedule with hours or a start date needs its timezone, "
                    'like "Europe/Amsterdam"'
                )
            return self
        try:
            self._zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError, ValueError:
            raise ValueError(
                f"{self.timezone!r} is not a timezone; use an IANA name like "
                f'"Europe/Amsterdam"'
            ) from None
        return self

    @property
    def always(self) -> bool:
        return self.hours is None and self.starts_on is None

    def open(self, now: datetime) -> bool:
        if self._zone is None:
            return True
        local = now.astimezone(self._zone)
        if self.starts_on is not None and local.date() < self.starts_on:
            return False
        return self.hours is None or self.hours.open(local.time())


class Delivery(BaseModel):
    """who a loop decides for: requests in its schedule, holding every
    condition of its audience, within its rollout. it never picks an option;
    the loop's state does. everyone else gets the fallback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audience: Annotated[list[Condition], Field(max_length=MAX_CONDITIONS)] = []
    rollout: Annotated[int, Field(ge=0, le=100)] = 100
    schedule: Schedule = Schedule()

    @property
    def everyone(self) -> bool:
        return not self.audience and self.rollout == 100 and self.schedule.always

    def decide(self, loop_id: str, unit: str, properties: dict, now: datetime) -> bool:
        """whether the loop decides for this request. rollout buckets the unit
        with the loop's id, so a unit keeps its bucket on a loop and is placed
        independently on every other one."""
        if not self.schedule.open(now):
            return False
        if not all(condition.holds(properties) for condition in self.audience):
            return False
        return self.rollout == 100 or bucket(f"{loop_id}:{unit}") < self.rollout


EVERYONE = Delivery()


def delivery_of(raw: dict[str, Any] | None) -> Delivery:
    return Delivery.model_validate(raw or {})
