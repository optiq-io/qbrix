"""unit tests for FeatureGate.decide — the traced form of control().

the point of these is the equivalence class: `control()` delegates to
`decide()`, and the dry-run endpoint calls `decide(trace=True)`. if those two
ever disagree the gate preview starts lying about live traffic, so the
agreement is asserted directly rather than assumed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from proxysvc.mod.gate.controller import FeatureGate, ExperimentFlagState

from factories import make_gate_config, make_rule


def _blackout(config):
    return patch.object(
        type(config.experiment.schedule), "is_in_active_schedule", return_value=False
    )


class TestDecideMatchesControl:
    """decide().arm must equal control(), traced or not, on every branch."""

    @pytest.mark.parametrize("trace", [False, True])
    @pytest.mark.parametrize(
        "enabled,rollout,rules,metadata",
        [
            (False, 100.0, None, {}),
            (True, 100.0, None, {}),
            (True, 0.0, None, {}),
            (True, 100.0, [make_rule(key="region", value="us")], {"region": "us"}),
            (True, 100.0, [make_rule(key="region", value="us")], {"region": "eu"}),
            (True, 0.0, [make_rule(key="region", value="us")], {"region": "us"}),
            (True, 100.0, [make_rule(key="region", value="us")], {}),
        ],
    )
    def test_agrees(self, enabled, rollout, rules, metadata, trace):
        config = make_gate_config(
            enabled=enabled, rollout_percentage=rollout, rules=rules
        )
        expected = FeatureGate.control(config, "ctx-1", metadata)
        decision = FeatureGate.decide(config, "ctx-1", metadata, trace=trace)

        assert decision.arm == expected

    @pytest.mark.parametrize("trace", [False, True])
    def test_agrees_in_blackout(self, trace):
        config = make_gate_config(enabled=True, rollout_percentage=100.0)
        with _blackout(config):
            expected = FeatureGate.control(config, "ctx-1", {})
            decision = FeatureGate.decide(config, "ctx-1", {}, trace=trace)

        assert decision.arm == expected
        assert decision.arm is not None


class TestReasons:

    def test_disabled(self):
        config = make_gate_config(enabled=False)
        decision = FeatureGate.decide(config, "ctx-1", {}, trace=True)

        assert decision.reason == "disabled"
        assert decision.arm is None

    def test_bandit_when_nothing_intervenes(self):
        config = make_gate_config(enabled=True, rollout_percentage=100.0)
        decision = FeatureGate.decide(config, "ctx-1", {}, trace=True)

        assert decision.reason == "bandit"
        assert decision.arm is None

    def test_rollout_excludes_at_zero(self):
        config = make_gate_config(enabled=True, rollout_percentage=0.0)
        decision = FeatureGate.decide(config, "ctx-1", {}, trace=True)

        # this is exactly how the console commits an arm: rollout 0 puts every
        # context outside the rollout, so the committed arm is always served
        assert decision.reason == "rollout"
        assert decision.arm is not None
        assert decision.arm.id == "arm-0"
        assert ExperimentFlagState.RNEG in decision.state

    def test_blackout_beats_rollout_in_reporting(self):
        config = make_gate_config(enabled=True, rollout_percentage=100.0)
        with _blackout(config):
            decision = FeatureGate.decide(config, "ctx-1", {}, trace=True)

        assert decision.reason == "blackout"

    def test_matching_rule_is_decisive(self):
        rules = [
            make_rule(key="region", value="eu"),
            make_rule(key="plan", value="pro"),
        ]
        config = make_gate_config(enabled=True, rollout_percentage=100.0, rules=rules)
        decision = FeatureGate.decide(
            config, "ctx-1", {"region": "us", "plan": "pro"}, trace=True
        )

        assert decision.reason == "rule"
        assert decision.matched_rule == 1
        assert decision.rule_matches == [False, True]


class TestTracing:

    def test_trace_reports_every_rule(self):
        rules = [
            make_rule(key="a", value="1"),
            make_rule(key="b", value="2"),
            make_rule(key="c", value="3"),
        ]
        config = make_gate_config(enabled=True, rollout_percentage=100.0, rules=rules)
        decision = FeatureGate.decide(
            config, "ctx-1", {"a": "1", "b": "x", "c": "3"}, trace=True
        )

        # every rule is reported even though the first match decided the outcome
        assert decision.rule_matches == [True, False, True]
        assert decision.matched_rule == 0

    def test_hot_path_does_not_evaluate_rules_it_does_not_need(self):
        rules = [make_rule(key="a", value="1")]
        config = make_gate_config(enabled=True, rollout_percentage=0.0, rules=rules)

        # outside the rollout the gate short-circuits before rules
        with patch.object(type(rules[0]), "eval", return_value=True) as ev:
            FeatureGate.decide(config, "ctx-1", {"a": "1"}, trace=False)

        ev.assert_not_called()

    def test_trace_does_not_change_the_outcome_it_reports(self):
        rules = [make_rule(key="a", value="1")]
        config = make_gate_config(enabled=True, rollout_percentage=0.0, rules=rules)

        untraced = FeatureGate.decide(config, "ctx-1", {"a": "1"}, trace=False)
        traced = FeatureGate.decide(config, "ctx-1", {"a": "1"}, trace=True)

        assert untraced.arm == traced.arm
        assert untraced.reason == traced.reason
        # ...even though tracing did surface the rule that never got consulted
        assert traced.rule_matches == [True]
        assert untraced.rule_matches == []
