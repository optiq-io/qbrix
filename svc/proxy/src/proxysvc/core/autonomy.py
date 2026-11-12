"""how much a connection may do on its own, per kind of change.

every kind a connection can make has a level and a default; reads have none.
a connection stores only the levels its person moved off the default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from typing import get_args

Level = Literal["own", "notify", "ask"]
LEVELS: tuple[Level, ...] = get_args(Level)


@dataclass(frozen=True, slots=True)
class Kind:
    name: str
    default: Level
    on_loop: bool


KINDS: tuple[Kind, ...] = (
    Kind("loop.create", "own", on_loop=False),
    Kind("metric.create", "own", on_loop=False),
    Kind("note.add", "own", on_loop=True),
    Kind("loop.launch", "ask", on_loop=True),
    Kind("cycle.start", "ask", on_loop=True),
    Kind("loop.retire", "ask", on_loop=True),
    Kind("loop.rename", "notify", on_loop=True),
    Kind("loop.pause", "notify", on_loop=True),
    Kind("loop.resume", "notify", on_loop=True),
    Kind("loop.commit", "notify", on_loop=True),
    Kind("loop.reopen", "notify", on_loop=True),
    Kind("cycle.reset", "notify", on_loop=True),
    Kind("delivery.update", "notify", on_loop=True),
    Kind("metric.delete", "notify", on_loop=False),
)

DEFAULTS: dict[str, Level] = {kind.name: kind.default for kind in KINDS}

ON_LOOP: tuple[str, ...] = tuple(kind.name for kind in KINDS if kind.on_loop)

NOT_BY_CONNECTIONS = frozenset(
    {
        "experiment.create",
        "experiment.update",
        "experiment.reset",
        "experiment.restore",
        "experiment.delete",
        "pool.create",
        "pool.update",
        "pool.delete",
        "gate.create",
        "gate.replace",
        "gate.patch",
        "gate.delete",
        "loop.delete",
        "connection.levels",
    }
)


def level_of(kind: str, overrides: Mapping[str, str]) -> Level:
    return overrides.get(kind, DEFAULTS[kind])


def levels(overrides: Mapping[str, str]) -> list[dict]:
    """every kind with its level and its default, in the order of KINDS."""
    return [
        {
            "kind": kind.name,
            "level": level_of(kind.name, overrides),
            "default": kind.default,
        }
        for kind in KINDS
    ]


def changed(overrides: Mapping[str, str]) -> list[dict]:
    """the kinds whose level is off its default."""
    return [entry for entry in levels(overrides) if entry["level"] != entry["default"]]


def by_level() -> dict[Level, list[str]]:
    """the defaults grouped by level, as a new connection starts."""
    return {
        level: [kind.name for kind in KINDS if kind.default == level]
        for level in LEVELS
    }


def normalise(overrides: Mapping[str, str]) -> dict[str, Level]:
    """the overrides worth storing: known kinds off their default."""
    return {
        kind: level
        for kind, level in overrides.items()
        if kind in DEFAULTS and level != DEFAULTS[kind]
    }


def check(levels_by_kind: Mapping[str, str]) -> None:
    """refuse a kind that takes no level, or a level that doesn't exist."""
    for kind, level in levels_by_kind.items():
        if kind not in DEFAULTS:
            raise ValueError(f"{kind!r} is not a kind of change that takes a level")
        if level not in LEVELS:
            raise ValueError(
                f"{level!r} is not a level; use one of {', '.join(LEVELS)}"
            )
