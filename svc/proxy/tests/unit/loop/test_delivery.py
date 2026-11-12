from __future__ import annotations

from datetime import datetime
from datetime import timezone

import pytest
from pydantic import ValidationError

from proxysvc.mod.loop.delivery import EVERYONE
from proxysvc.mod.loop.delivery import MAX_CONDITIONS
from proxysvc.mod.loop.delivery import Delivery
from proxysvc.mod.loop.delivery import delivery_of

pytestmark = pytest.mark.unit

NOON_UTC = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
MOBILE_NL = [
    {"property": "device", "operator": "is", "value": "mobile"},
    {"property": "country", "operator": "in", "value": ["NL", "BE"]},
]


def _decides(delivery: dict, properties: dict, *, unit="u-1", now=NOON_UTC) -> bool:
    return Delivery.model_validate(delivery).decide("loop-1", unit, properties, now)


class TestEveryone:
    def test_the_default_decides_for_everyone_always(self):
        assert EVERYONE.everyone
        assert EVERYONE.decide("loop-1", "u-1", {}, NOON_UTC)

    def test_a_loop_without_a_delivery_reads_as_everyone(self):
        assert delivery_of({}) == EVERYONE
        assert delivery_of(None) == EVERYONE

    def test_any_part_set_is_not_everyone(self):
        assert not Delivery(rollout=50).everyone
        assert not delivery_of({"audience": MOBILE_NL}).everyone
        assert delivery_of({"schedule": {"timezone": "UTC"}}).everyone


class TestAudience:
    def test_every_condition_must_hold(self):
        audience = {"audience": MOBILE_NL}
        assert _decides(audience, {"device": "mobile", "country": "NL"})
        assert not _decides(audience, {"device": "desktop", "country": "NL"})
        assert not _decides(audience, {"device": "mobile", "country": "DE"})

    def test_a_missing_property_fails_its_condition_even_when_negative(self):
        not_nl = {
            "audience": [{"property": "country", "operator": "is_not", "value": "NL"}]
        }
        assert _decides(not_nl, {"country": "DE"})
        assert not _decides(not_nl, {})
        not_in = {
            "audience": [{"property": "country", "operator": "not_in", "value": ["NL"]}]
        }
        assert not _decides(not_in, {})

    def test_a_type_mismatch_fails_its_condition(self):
        orders = {"audience": [{"property": "orders", "operator": "gte", "value": 3}]}
        assert _decides(orders, {"orders": 4})
        assert not _decides(orders, {"orders": "4"})

    @pytest.mark.parametrize(
        "condition, message",
        [
            ({"property": "c", "operator": "in", "value": "NL"}, "takes a list"),
            ({"property": "c", "operator": "is", "value": ["NL"]}, "takes one value"),
            ({"property": "c", "operator": "in", "value": []}, "takes 1 to"),
            ({"property": "c", "operator": "eq", "value": "NL"}, "operator"),
            ({"property": "", "operator": "is", "value": "NL"}, "property"),
            ({"property": "c", "operator": "is", "value": {"a": 1}}, "value"),
        ],
    )
    def test_a_condition_that_cant_hold_is_refused(self, condition, message):
        with pytest.raises(ValidationError, match=message):
            Delivery.model_validate({"audience": [condition]})

    def test_at_most_twenty_conditions(self):
        condition = {"property": "c", "operator": "is", "value": "NL"}
        Delivery.model_validate({"audience": [condition] * MAX_CONDITIONS})
        with pytest.raises(ValidationError):
            Delivery.model_validate({"audience": [condition] * (MAX_CONDITIONS + 1)})


class TestRollout:
    def test_none_and_all(self):
        units = [f"u-{n}" for n in range(200)]
        assert not any(_decides({"rollout": 0}, {}, unit=unit) for unit in units)
        assert all(_decides({"rollout": 100}, {}, unit=unit) for unit in units)

    def test_raising_it_only_adds_units(self):
        units = [f"u-{n}" for n in range(1000)]
        at_10 = {unit for unit in units if _decides({"rollout": 10}, {}, unit=unit)}
        at_50 = {unit for unit in units if _decides({"rollout": 50}, {}, unit=unit)}
        assert at_10 < at_50
        assert 50 < len(at_10) < 150
        assert 400 < len(at_50) < 600

    def test_a_unit_is_placed_independently_on_each_loop(self):
        half = Delivery(rollout=50)
        units = [f"u-{n}" for n in range(1000)]
        on_one = {u for u in units if half.decide("loop-1", u, {}, NOON_UTC)}
        on_other = {u for u in units if half.decide("loop-2", u, {}, NOON_UTC)}
        assert on_one != on_other
        assert 150 < len(on_one & on_other) < 350

    @pytest.mark.parametrize("rollout", [-1, 101])
    def test_out_of_range_is_refused(self, rollout):
        with pytest.raises(ValidationError):
            Delivery(rollout=rollout)


def _at(hour: int, minute: int = 0, day: int = 12) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


class TestSchedule:
    def test_hours_run_from_start_until_end(self):
        office = {
            "schedule": {
                "hours": {"start": "09:00", "end": "18:00"},
                "timezone": "UTC",
            }
        }
        assert not _decides(office, {}, now=_at(8, 59))
        assert _decides(office, {}, now=_at(9, 0))
        assert _decides(office, {}, now=_at(17, 59))
        assert not _decides(office, {}, now=_at(18, 0))

    def test_hours_can_run_past_midnight(self):
        night = {
            "schedule": {"hours": {"start": "22:00", "end": "06:00"}, "timezone": "UTC"}
        }
        assert _decides(night, {}, now=_at(23))
        assert _decides(night, {}, now=_at(5, 59))
        assert not _decides(night, {}, now=_at(6))
        assert not _decides(night, {}, now=_at(12))

    def test_hours_are_read_in_the_schedules_timezone(self):
        amsterdam = {
            "schedule": {
                "hours": {"start": "09:00", "end": "10:00"},
                "timezone": "Europe/Amsterdam",
            }
        }
        assert _decides(amsterdam, {}, now=_at(8, 30))
        assert not _decides(amsterdam, {}, now=_at(9, 30))

    def test_a_start_date_holds_until_that_day_in_its_timezone(self):
        starts = {
            "schedule": {"starts_on": "2026-12-01", "timezone": "Europe/Amsterdam"}
        }
        assert not _decides(
            starts, {}, now=datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc)
        )
        assert _decides(
            starts, {}, now=datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc)
        )

    @pytest.mark.parametrize(
        "schedule, message",
        [
            ({"hours": {"start": "09:00", "end": "18:00"}}, "needs its timezone"),
            ({"starts_on": "2026-12-01"}, "needs its timezone"),
            ({"timezone": "Mars/Base"}, "is not a timezone"),
            (
                {"hours": {"start": "9:00", "end": "18:00"}, "timezone": "UTC"},
                "a time like",
            ),
            (
                {"hours": {"start": "09:00", "end": "09:00"}, "timezone": "UTC"},
                "the same",
            ),
            ({"ends_on": "2026-12-31", "timezone": "UTC"}, "ends_on"),
        ],
    )
    def test_a_schedule_that_cant_be_read_is_refused(self, schedule, message):
        with pytest.raises(ValidationError, match=message):
            Delivery.model_validate({"schedule": schedule})


class TestOrder:
    def test_schedule_audience_and_rollout_all_must_let_it_through(self):
        delivery = {
            "audience": MOBILE_NL,
            "rollout": 100,
            "schedule": {
                "hours": {"start": "09:00", "end": "18:00"},
                "timezone": "UTC",
            },
        }
        mobile_nl = {"device": "mobile", "country": "NL"}
        assert _decides(delivery, mobile_nl, now=_at(12))
        assert not _decides(delivery, mobile_nl, now=_at(20))
        assert not _decides({**delivery, "rollout": 0}, mobile_nl, now=_at(12))


def test_it_round_trips_through_json():
    delivery = Delivery.model_validate(
        {
            "audience": MOBILE_NL,
            "rollout": 30,
            "schedule": {
                "hours": {"start": "22:00", "end": "06:00"},
                "starts_on": "2026-12-01",
                "timezone": "Europe/Amsterdam",
            },
        }
    )
    again = Delivery.model_validate_json(delivery.model_dump_json())
    assert again == delivery
    december = datetime(2026, 12, 2, 23, 0, tzinfo=timezone.utc)
    assert again.decide(
        "loop-1", "u-1", {"device": "mobile", "country": "NL"}, december
    )
