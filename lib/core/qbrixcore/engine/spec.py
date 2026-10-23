from __future__ import annotations

import re
from dataclasses import dataclass

ACCEPTED_FORMS = "spinoza, spinoza:1 or spinoza:1.3"

_SPEC = re.compile(r"^(?P<name>[a-z]+)(?::(?P<major>\d+)(?:\.(?P<minor>\d+))?)?$")


class EngineError(ValueError):
    """raised when an engine spec, engine or resolution request is refused."""


@dataclass(frozen=True, order=True)
class EngineVersion:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True)
class EngineSpec:
    """an engine as a cycle names it: the latest, a major, or an exact minor."""

    name: str
    major: int | None = None
    minor: int | None = None

    def __post_init__(self):
        if self.minor is not None and self.major is None:
            raise EngineError("an engine spec with a minor needs its major")

    @classmethod
    def parse(cls, text: str) -> EngineSpec:
        match = _SPEC.match(text)
        if match is None:
            raise EngineError(
                f"invalid engine spec {text!r}; accepted forms: {ACCEPTED_FORMS}"
            )
        major = match.group("major")
        minor = match.group("minor")
        return cls(
            name=match.group("name"),
            major=int(major) if major is not None else None,
            minor=int(minor) if minor is not None else None,
        )

    def __str__(self) -> str:
        if self.major is None:
            return self.name
        if self.minor is None:
            return f"{self.name}:{self.major}"
        return f"{self.name}:{self.major}.{self.minor}"
