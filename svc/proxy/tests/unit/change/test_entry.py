from __future__ import annotations

import pytest

from proxysvc.mod.change.entry import VERBS
from proxysvc.mod.change.entry import diff
from proxysvc.mod.change.undo import NOT_UNDOABLE
from proxysvc.mod.change.undo import UNDOABLE_KINDS

pytestmark = pytest.mark.unit


def test_every_kind_has_its_verb():
    assert (UNDOABLE_KINDS | NOT_UNDOABLE.keys()) <= VERBS.keys()


def test_a_change_with_one_side_has_nothing_to_compare():
    assert diff(None, {"name": "a"}) == []
    assert diff({"name": "a"}, None) == []


def test_unchanged_fields_stay_out():
    same = {"name": "a", "state": "live", "updated_at": "1"}

    assert diff(same, {**same, "updated_at": "2"}) == []


def test_options_added_and_removed_have_one_side():
    before = {"options": [{"key": "a", "name": "A"}, {"key": "b", "name": "B"}]}
    after = {"options": [{"key": "b", "name": "B"}, {"key": "c", "name": "C"}]}

    assert diff(before, after) == [
        {"field": "option", "before": None, "after": "C"},
        {"field": "option", "before": "A", "after": None},
    ]


def test_a_loops_metric_reads_by_name():
    before = {"metric": {"id": "1", "name": "purchase"}}
    after = {"metric": {"id": "2", "name": "signup"}}

    assert diff(before, after) == [
        {"field": "metric", "before": "purchase", "after": "signup"}
    ]


def test_a_metrics_window_reads_as_a_length():
    assert diff({"window_seconds": 86400}, {"window_seconds": 3600}) == [
        {"field": "window", "before": "1d", "after": "1h"}
    ]


def test_a_value_that_is_not_text_reads_as_json():
    assert diff({"audience": {"rollout": 10}}, {"audience": {"rollout": 20}}) == [
        {"field": "audience", "before": '{"rollout": 10}', "after": '{"rollout": 20}'}
    ]
