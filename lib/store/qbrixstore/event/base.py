from __future__ import annotations

import json
from dataclasses import MISSING
from dataclasses import Field
from dataclasses import fields
from typing import Any
from typing import get_origin
from typing import get_type_hints


class EventDecodeError(ValueError):
    """a stream entry could not be decoded into its event type."""


_TYPES: dict[type, dict[str, Any]] = {}


def _types(cls: type) -> dict[str, Any]:
    hints = _TYPES.get(cls)
    if hints is None:
        hints = get_type_hints(cls)
        _TYPES[cls] = hints
    return hints


def _encode(annotation: Any, value: Any) -> str:
    # dispatch on the declared type, not on the value: a list/dict field may
    # legitimately hold None (proxy emits a null context_vector), and that has
    # to encode as json "null" for the decoder's empty-collection fallback to
    # see it. str(None) would be "None", which is not json.
    origin = get_origin(annotation) or annotation
    if origin is bool:
        return "1" if value else "0"
    if origin is list or origin is dict:
        return json.dumps(value)
    return str(value)


def _decode(annotation: Any, raw: str) -> Any:
    origin = get_origin(annotation) or annotation
    if origin is bool:
        return raw == "1"
    if origin is int:
        return int(raw)
    if origin is float:
        return float(raw)
    if origin is list:
        return json.loads(raw) or []
    if origin is dict:
        return json.loads(raw) or {}
    return raw


def _has_default(field: Field) -> bool:
    return field.default is not MISSING or field.default_factory is not MISSING


class Event:
    """base for events carried on redis streams.

    redis stores stream entries as flat string->string maps, so every field is
    encoded on the way out and parsed on the way back. both directions are
    derived from the subclass's dataclass fields, which is what stops them
    drifting apart.

    decoding is tolerant in one direction only. unknown keys are ignored and an
    absent optional field falls back to its default, so a field added by a
    newer publisher — or dropped by an older one — does not break consumers
    still draining entries published across a deploy. an absent *required*
    field still raises: that is data loss, not rollout skew.
    """

    def to_dict(self) -> dict[str, str]:
        hints = _types(type(self))
        return {
            f.name: _encode(hints[f.name], getattr(self, f.name)) for f in fields(self)
        }

    @classmethod
    def from_dict(cls, data: dict) -> Any:
        hints = _types(cls)
        kwargs: dict[str, Any] = {}

        for field in fields(cls):  # noqa
            raw = data.get(field.name)

            if raw is None:
                if _has_default(field):
                    continue
                raise EventDecodeError(
                    f"{cls.__name__}: missing required field {field.name!r}"
                )

            # a flat string map has no null, so an optional field that was never
            # set round-trips as "". required fields keep "" as a real value —
            # audit events legitimately carry an empty actor_id.
            if raw == "" and _has_default(field):
                continue

            try:
                kwargs[field.name] = _decode(hints[field.name], raw)
            except (TypeError, ValueError) as e:
                raise EventDecodeError(
                    f"{cls.__name__}: cannot decode field {field.name!r}: {e}"
                ) from e

        return cls(**kwargs)
