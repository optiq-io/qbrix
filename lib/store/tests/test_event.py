"""codec and schema-tolerance tests for the stream event base.

redis stream entries are flat str->str maps written by one service and read by
another, often across a deploy. these tests pin the wire format and the decode
tolerance that makes a rolling deploy survivable.
"""

from __future__ import annotations

import pytest

from qbrixstore.event import AuditEvent
from qbrixstore.event import EventDecodeError
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent


def a_selection(**overrides) -> SelectionEvent:
    kwargs = dict(
        tenant_id="t1",
        experiment_id="exp",
        request_id="req",
        event_id="evt",
        arm_id="arm",
        arm_name="Arm A",
        arm_index=2,
        is_default=False,
        context_id="ctx",
        context_vector=[0.5, 1.0],
        context_metadata={"k": "v"},
        timestamp_ms=1_700,
        policy="beta_ts",
    )
    kwargs.update(overrides)
    return SelectionEvent(**kwargs)


def a_feedback() -> FeedbackEvent:
    return FeedbackEvent(
        tenant_id="t1",
        experiment_id="exp",
        request_id="req",
        arm_index=1,
        reward=0.25,
        context_id="ctx",
        context_vector=[],
        context_metadata={},
        timestamp_ms=9,
    )


def an_audit(**overrides) -> AuditEvent:
    kwargs = dict(
        name="experiment.created",
        tenant_id="t1",
        actor_id="user-1",
        resource_type="experiment",
        resource_id="exp",
        payload={"a": 1},
        timestamp_ms=5,
    )
    kwargs.update(overrides)
    return AuditEvent(**kwargs)


class TestWireFormat:
    def test_every_value_is_a_string(self):
        assert all(isinstance(v, str) for v in a_selection().to_dict().values())

    def test_scalars_encode_as_redis_expects(self):
        encoded = a_selection().to_dict()
        assert encoded["arm_index"] == "2"
        assert encoded["is_default"] == "0"
        assert encoded["timestamp_ms"] == "1700"

    def test_bool_does_not_leak_python_repr(self):
        assert a_selection(is_default=True).to_dict()["is_default"] == "1"

    def test_collections_encode_as_json(self):
        encoded = a_selection().to_dict()
        assert encoded["context_vector"] == "[0.5, 1.0]"
        assert encoded["context_metadata"] == '{"k": "v"}'

    def test_none_collection_encodes_as_json_null(self):
        """a list/dict field can legitimately hold None — proxy emits a null
        context_vector when the selection token carries no vector. it has to
        encode as json "null"; str(None) would be "None", which no consumer can
        parse, and the entry would wedge the consumer loop on redelivery."""
        encoded = a_selection(context_vector=None, context_metadata=None).to_dict()

        assert encoded["context_vector"] == "null"
        assert encoded["context_metadata"] == "null"

    def test_none_collection_round_trips_to_empty(self):
        event = a_selection(context_vector=None, context_metadata=None)

        decoded = SelectionEvent.from_dict(event.to_dict())

        assert decoded.context_vector == []
        assert decoded.context_metadata == {}

    @pytest.mark.parametrize("event", [a_selection(), a_feedback(), an_audit()])
    def test_round_trip_is_lossless(self, event):
        assert type(event).from_dict(event.to_dict()) == event


class TestDecodeTolerance:
    """a publisher and its consumers are deployed separately, so a consumer will
    read entries written by both the previous and the next schema."""

    def test_unknown_key_is_ignored(self):
        event = a_selection()
        data = event.to_dict() | {"field_from_a_newer_publisher": "x"}

        assert SelectionEvent.from_dict(data) == event

    def test_absent_optional_field_falls_back_to_its_default(self):
        data = a_selection().to_dict()
        del data["event_id"]

        assert SelectionEvent.from_dict(data).event_id

    def test_defaulted_field_is_distinct_per_decode(self):
        """event_id is billing's dedup key, so two entries that both lack one
        must not collapse onto a shared constant."""
        data = a_selection().to_dict()
        del data["event_id"]

        first = SelectionEvent.from_dict(data)
        second = SelectionEvent.from_dict(data)

        assert first.event_id != second.event_id

    def test_empty_optional_field_is_treated_as_absent(self):
        data = a_selection().to_dict() | {"event_id": ""}

        assert SelectionEvent.from_dict(data).event_id

    def test_empty_required_field_stays_empty(self):
        """audit events legitimately carry an empty actor_id for system actions,
        so "" must decode as a value rather than as a missing field."""
        event = an_audit(actor_id="")

        assert AuditEvent.from_dict(event.to_dict()).actor_id == ""

    def test_missing_required_field_raises(self):
        data = a_selection().to_dict()
        del data["policy"]

        with pytest.raises(EventDecodeError, match="policy"):
            SelectionEvent.from_dict(data)

    def test_undecodable_value_raises(self):
        data = a_selection().to_dict() | {"arm_index": "not-a-number"}

        with pytest.raises(EventDecodeError, match="arm_index"):
            SelectionEvent.from_dict(data)

    def test_null_collections_decode_to_empties(self):
        data = a_selection().to_dict() | {
            "context_vector": "null",
            "context_metadata": "null",
        }

        decoded = SelectionEvent.from_dict(data)

        assert decoded.context_vector == []
        assert decoded.context_metadata == {}
