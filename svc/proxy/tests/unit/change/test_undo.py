from __future__ import annotations

import pytest

from proxysvc.mod.change.undo import is_undoable
from proxysvc.mod.change.undo import not_undoable_reason

pytestmark = pytest.mark.unit

FIRST = {"cycle": {"id": "c1", "number": 1}}
SECOND = {"cycle": {"id": "c2", "number": 2}}
DRAFT = {"cycle": None}


@pytest.mark.parametrize(
    "before, after", [(FIRST, FIRST), (DRAFT, DRAFT)], ids=["same cycle", "draft"]
)
def test_a_context_change_that_keeps_the_cycle_undoes(before, after):
    assert is_undoable("context.update", before, after)
    assert not_undoable_reason("context.update", before, after) is None


def test_a_context_change_that_started_a_cycle_does_not():
    assert not is_undoable("context.update", FIRST, SECOND)
    assert "started a new cycle" in not_undoable_reason("context.update", FIRST, SECOND)


def test_other_kinds_answer_by_kind_alone():
    assert is_undoable("delivery.update", FIRST, SECOND)
    assert not is_undoable("cycle.start", FIRST, FIRST)
    assert "begins fresh learning" in not_undoable_reason("cycle.start")
