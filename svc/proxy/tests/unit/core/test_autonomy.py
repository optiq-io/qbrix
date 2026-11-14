from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import proxysvc.mod
from proxysvc.core import autonomy
from proxysvc.core.actor import Actor
from proxysvc.mod.change.serialize import VERBS
from proxysvc.mod.change.undo import NOT_UNDOABLE
from proxysvc.mod.change.undo import UNDOABLE_KINDS
from proxysvc.mod.connection.service import ConnectionPrincipal

pytestmark = pytest.mark.unit

_KIND = re.compile(
    r"^(loop|cycle|delivery|context|metric|note|experiment|pool|gate|connection)\.[a-z]+$"
)


def _kinds_in_source() -> set[str]:
    """every string in the services' code shaped like a kind of change, leaving
    out audit event names, which are passed as name=."""
    found = set()
    for path in Path(proxysvc.mod.__path__[0]).rglob("*.py"):
        tree = ast.parse(path.read_text())
        audit = {
            id(keyword.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "name"
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _KIND.match(node.value)
                and id(node) not in audit
            ):
                found.add(node.value)
    return found


def test_every_recorded_kind_has_a_level_or_is_never_made_by_a_connection():
    known = autonomy.DEFAULTS.keys() | autonomy.NOT_BY_CONNECTIONS
    assert not autonomy.DEFAULTS.keys() & autonomy.NOT_BY_CONNECTIONS
    assert UNDOABLE_KINDS | NOT_UNDOABLE.keys() | VERBS.keys() == known
    recorded = _kinds_in_source()
    assert autonomy.DEFAULTS.keys() <= recorded
    assert recorded <= known


def test_the_defaults_are_the_definitions():
    assert autonomy.by_level() == {
        "own": ["loop.create", "metric.create", "note.add"],
        "notify": [
            "loop.rename",
            "loop.pause",
            "loop.resume",
            "loop.commit",
            "loop.reopen",
            "cycle.reset",
            "delivery.update",
            "context.update",
            "metric.delete",
        ],
        "ask": ["loop.launch", "cycle.start", "loop.retire"],
    }


def test_a_connection_on_its_defaults_has_nothing_changed():
    assert autonomy.changed({}) == []
    assert [entry["level"] for entry in autonomy.levels({})] == [
        kind.default for kind in autonomy.KINDS
    ]


def test_an_override_reads_over_its_default():
    overrides = {"loop.launch": "notify"}

    assert autonomy.level_of("loop.launch", overrides) == "notify"
    assert autonomy.level_of("cycle.start", overrides) == "ask"
    assert autonomy.changed(overrides) == [
        {"kind": "loop.launch", "level": "notify", "default": "ask"}
    ]


def test_only_levels_off_their_default_are_kept():
    assert autonomy.normalise(
        {"loop.launch": "ask", "note.add": "ask", "loop.gone": "own"}
    ) == {"note.add": "ask"}


@pytest.mark.parametrize(
    "levels",
    [{"experiment.update": "own"}, {"loop.read": "own"}, {"loop.launch": "never"}],
)
def test_a_read_an_old_kind_or_an_unknown_level_is_refused(levels):
    with pytest.raises(ValueError):
        autonomy.check(levels)


@pytest.mark.parametrize(
    "levels, expected",
    [
        ({}, "ask"),
        ({"cycle.start": "notify"}, "notify"),
        ({"cycle.start": "own"}, "notify"),
        ({"cycle.start": "own", "context.update": "own"}, "own"),
        ({"cycle.start": "own", "context.update": "ask"}, "ask"),
    ],
)
def test_a_change_that_is_also_another_kind_acts_at_the_strictest(levels, expected):
    principal = ConnectionPrincipal(
        actor=Actor.member("user-ada"), tenant_id="t", role="member", levels=levels
    )

    assert principal.acting("context.update", "cycle.start").level == expected
    assert principal.acting("context.update").level == levels.get(
        "context.update", "notify"
    )
