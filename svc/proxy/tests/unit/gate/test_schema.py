"""unit tests for gate request schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proxysvc.mod.gate.schema import GateConfigRequest
from proxysvc.mod.gate.schema import RuleRequest


class TestRuleRequestKey:

    def test_empty_key_rejected(self):
        with pytest.raises(ValidationError):
            RuleRequest(key="", operator="in", value="x")

    def test_non_empty_key_accepted(self):
        rule = RuleRequest(key="country", operator="in", value="US")
        assert rule.key == "country"


class TestGateConfigScheduleRange:

    def test_start_after_end_rejected(self):
        with pytest.raises(ValidationError):
            GateConfigRequest(schedule_start="2026-02-02", schedule_end="2026-02-01")

    def test_equal_dates_rejected(self):
        with pytest.raises(ValidationError):
            GateConfigRequest(schedule_start="2026-02-02", schedule_end="2026-02-02")

    def test_valid_range_accepted(self):
        cfg = GateConfigRequest(schedule_start="2026-02-01", schedule_end="2026-02-02")
        assert cfg.schedule_start == "2026-02-01"

    def test_only_start_accepted(self):
        cfg = GateConfigRequest(schedule_start="2026-02-01")
        assert cfg.schedule_end is None

    def test_only_end_accepted(self):
        cfg = GateConfigRequest(schedule_end="2026-02-02")
        assert cfg.schedule_start is None

    def test_no_schedule_accepted(self):
        cfg = GateConfigRequest()
        assert cfg.schedule_start is None
        assert cfg.schedule_end is None

    def test_mixed_iso_and_date_compared(self):
        # tz-aware datetime start vs date-only end must still validate
        cfg = GateConfigRequest(
            schedule_start="2026-02-01T00:00:00+00:00",
            schedule_end="2026-02-02",
        )
        assert cfg.schedule_end == "2026-02-02"
