"""stream topology registry.

the registry's whole purpose is that stream-wide invariants are derived once
rather than re-applied at each call site, so these tests assert the derivation
and then pin the values it currently produces.
"""

from __future__ import annotations

import pytest

from qbrixstore.event import AuditEvent
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import MetricEvent
from qbrixstore.event import SelectionEvent
from qbrixstore.stream import topology
from qbrixstore.stream.topology import StreamSpec


class TestDeleteOnAck:
    def test_single_group_stream_deletes_on_ack(self):
        spec = StreamSpec(
            name="s", event=AuditEvent, max_len=10, groups=frozenset({"only"})
        )

        assert spec.delete_on_ack is True

    def test_adding_a_second_group_flips_it(self):
        """the invariant that motivated the registry: xdel removes an entry for
        every group, so a stream gaining a second consumer must stop deleting —
        and gaining that consumer is the only edit needed to make it so."""
        one = StreamSpec(
            name="s", event=AuditEvent, max_len=10, groups=frozenset({"a"})
        )
        two = StreamSpec(
            name="s", event=AuditEvent, max_len=10, groups=frozenset({"a", "b"})
        )

        assert one.delete_on_ack is True
        assert two.delete_on_ack is False


class TestStartIds:
    def test_default_start_id_drains_history(self):
        spec = StreamSpec(
            name="s", event=AuditEvent, max_len=10, groups=frozenset({"a"})
        )

        assert spec.start_id("a") == "0"

    def test_per_group_override(self):
        spec = StreamSpec(
            name="s",
            event=AuditEvent,
            max_len=10,
            groups=frozenset({"a", "b"}),
            start_ids={"b": "$"},
        )

        assert spec.start_id("a") == "0"
        assert spec.start_id("b") == "$"

    def test_start_id_for_an_undeclared_group_is_rejected(self):
        """a start id keyed on a typo'd group would silently do nothing."""
        with pytest.raises(ValueError, match="undeclared"):
            StreamSpec(
                name="s",
                event=AuditEvent,
                max_len=10,
                groups=frozenset({"a"}),
                start_ids={"typo": "$"},
            )


class TestGroupMembership:
    def test_declared_group_is_accepted(self):
        topology.SELECTION.require_group("metering")

    def test_undeclared_group_is_rejected(self):
        with pytest.raises(ValueError, match="not a declared consumer group"):
            topology.SELECTION.require_group("cortex")

    def test_a_stream_needs_at_least_one_group(self):
        with pytest.raises(ValueError, match="at least one group"):
            StreamSpec(name="s", event=AuditEvent, max_len=10, groups=frozenset())


class TestDeployedTopology:
    """pins what the registry currently produces.

    the registry was introduced runtime-neutral, so these are the values the
    hand-rolled call sites used before the registry existed. a change here is a
    change to production behaviour and should be deliberate.
    """

    def test_feedback(self):
        spec = topology.FEEDBACK
        assert spec.name == "qbrix:feedback"
        assert spec.event is FeedbackEvent
        assert spec.groups == frozenset({"cortex", "trace"})
        assert spec.max_len == 150_000
        assert spec.start_id("cortex") == "0"
        assert spec.start_id("trace") == "0"

    def test_feedback_does_not_delete_on_ack(self):
        """a cortex ack must not delete an entry trace has not read yet."""
        assert topology.FEEDBACK.delete_on_ack is False

    def test_selection(self):
        spec = topology.SELECTION
        assert spec.name == "qbrix:selection"
        assert spec.event is SelectionEvent
        assert spec.groups == frozenset({"trace", "metering"})
        assert spec.max_len == 200_000
        assert spec.delete_on_ack is False
        assert spec.start_id("metering") == "$"
        assert spec.start_id("trace") == "0"

    def test_audit(self):
        spec = topology.AUDIT
        assert spec.name == "qbrix:audit"
        assert spec.event is AuditEvent
        assert spec.groups == frozenset({"trace"})
        assert spec.max_len == 100_000
        assert spec.delete_on_ack is True
        assert spec.start_id("trace") == "0"

    def test_event(self):
        spec = topology.EVENT
        assert spec.name == "qbrix:event"
        assert spec.event is MetricEvent
        assert spec.groups == frozenset({"trace"})
        assert spec.max_len == 100_000
        assert spec.delete_on_ack is True
        assert spec.start_id("trace") == "0"

    def test_registry_is_complete(self):
        assert set(topology.ALL) == {
            topology.FEEDBACK,
            topology.SELECTION,
            topology.AUDIT,
            topology.EVENT,
        }


class TestMemoryBudget:
    """redis runs noeviction, so a stream at its cap that doesn't fit refuses
    every write instead of trimming. bytes per entry are redis MEMORY USAGE at
    the widest context (64 dims), measured on redis 7.4; audit carries headroom
    for larger payloads, and a metric event is measured with a 256-character
    unit and id."""

    MAXMEMORY = 1024**3
    WORST_BYTES_PER_ENTRY = {
        topology.FEEDBACK: 1_930,
        topology.SELECTION: 1_930,
        topology.AUDIT: 600,
        topology.EVENT: 1_030,
    }

    def test_every_stream_has_a_measured_size(self):
        assert set(self.WORST_BYTES_PER_ENTRY) == set(topology.ALL)

    def test_all_streams_full_fit_with_room_for_learning(self):
        full = sum(
            spec.max_len * self.WORST_BYTES_PER_ENTRY[spec] for spec in topology.ALL
        )
        assert full <= 0.8 * self.MAXMEMORY
