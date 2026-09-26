"""stream topology registry.

the registry's whole purpose is that stream-wide invariants are derived once
rather than re-applied at each call site, so these tests assert the derivation
and then pin the values it currently produces.
"""

from __future__ import annotations

import pytest

from qbrixstore.event import AuditEvent
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent
from qbrixstore.stream import topology
from qbrixstore.stream.topology import StreamSpec


class TestDeleteOnAck:
    def test_single_group_stream_deletes_on_ack(self):
        spec = StreamSpec(name="s", event=AuditEvent, groups=frozenset({"only"}))

        assert spec.delete_on_ack is True

    def test_adding_a_second_group_flips_it(self):
        """the invariant that motivated the registry: xdel removes an entry for
        every group, so a stream gaining a second consumer must stop deleting —
        and gaining that consumer is the only edit needed to make it so."""
        one = StreamSpec(name="s", event=AuditEvent, groups=frozenset({"a"}))
        two = StreamSpec(name="s", event=AuditEvent, groups=frozenset({"a", "b"}))

        assert one.delete_on_ack is True
        assert two.delete_on_ack is False

    def test_override_wins_over_the_derivation(self):
        spec = StreamSpec(
            name="s",
            event=AuditEvent,
            groups=frozenset({"a", "b"}),
            delete_on_ack_override=True,
        )

        assert spec.delete_on_ack is True


class TestStartIds:
    def test_default_start_id_drains_history(self):
        spec = StreamSpec(name="s", event=AuditEvent, groups=frozenset({"a"}))

        assert spec.start_id("a") == "0"

    def test_per_group_override(self):
        spec = StreamSpec(
            name="s",
            event=AuditEvent,
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
            StreamSpec(name="s", event=AuditEvent, groups=frozenset())


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
        assert spec.max_len == 1_000_000
        assert spec.start_id("cortex") == "0"
        assert spec.start_id("trace") == "0"

    def test_feedback_pins_delete_on_ack(self):
        """fanned out, so this would derive to False. pinned True until the stream
        has the MAXLEN that the flip requires; the pin is explicit so the
        divergence cannot be mistaken for the derivation misbehaving."""
        assert len(topology.FEEDBACK.groups) > 1
        assert topology.FEEDBACK.delete_on_ack_override is True
        assert topology.FEEDBACK.delete_on_ack is True

    def test_selection(self):
        spec = topology.SELECTION
        assert spec.name == "qbrix:selection"
        assert spec.event is SelectionEvent
        assert spec.groups == frozenset({"trace", "metering"})
        assert spec.max_len == 1_000_000
        assert spec.delete_on_ack is False
        assert spec.start_id("metering") == "$"
        assert spec.start_id("trace") == "0"

    def test_audit(self):
        spec = topology.AUDIT
        assert spec.name == "qbrix:audit"
        assert spec.event is AuditEvent
        assert spec.groups == frozenset({"trace"})
        assert spec.max_len == 1_000_000
        assert spec.delete_on_ack is True
        assert spec.start_id("trace") == "0"

    def test_registry_is_complete(self):
        assert set(topology.ALL) == {
            topology.FEEDBACK,
            topology.SELECTION,
            topology.AUDIT,
        }
