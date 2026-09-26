"""unit tests for FeatureGate controller logic."""

from __future__ import annotations

from unittest.mock import patch

from proxysvc.mod.gate.controller import FeatureGate, ExperimentFlagState
from proxysvc.mod.gate.model.base import BaseArmModel

from factories import make_gate_config, make_rule


class TestRenderFeatureFlags:

    def test_enabled_active_rollout_positive(self):
        config = make_gate_config(enabled=True, rollout_percentage=100.0)
        state = FeatureGate.render_feature_flags(config, "any-user")

        assert ExperimentFlagState.ENABLED in state
        assert ExperimentFlagState.ACTIVE in state
        assert ExperimentFlagState.RPOS in state
        assert ExperimentFlagState.DISABLED not in state
        assert ExperimentFlagState.BLACKOUT not in state
        assert ExperimentFlagState.RNEG not in state

    def test_disabled_sets_flag(self):
        config = make_gate_config(enabled=False)
        state = FeatureGate.render_feature_flags(config, "any-user")

        assert ExperimentFlagState.DISABLED in state
        assert ExperimentFlagState.ENABLED not in state

    def test_blackout_sets_flag(self):
        config = make_gate_config(enabled=True)
        # patch the method on the instance to simulate inactive schedule
        with patch.object(
            type(config.experiment.schedule),
            "is_in_active_schedule",
            return_value=False,
        ):
            state = FeatureGate.render_feature_flags(config, "any-user")

        assert ExperimentFlagState.BLACKOUT in state
        assert ExperimentFlagState.ACTIVE not in state

    def test_rollout_negative_sets_flag(self):
        # rollout=0% means no one gets in
        config = make_gate_config(enabled=True, rollout_percentage=0.0)
        state = FeatureGate.render_feature_flags(config, "any-user")

        assert ExperimentFlagState.RNEG in state
        assert ExperimentFlagState.RPOS not in state


class TestRenderRules:

    def test_no_rules_returns_none(self):
        config = make_gate_config(rules=[])
        result = FeatureGate.render_rules(config, {"region": "us"})
        assert result is None

    def test_first_matching_rule_returned(self):
        rule1 = make_rule(key="region", operator="eq", value="eu")
        rule2 = make_rule(key="region", operator="eq", value="us")
        config = make_gate_config(rules=[rule1, rule2])

        result = FeatureGate.render_rules(config, {"region": "us"})
        assert result is rule2

    def test_no_match_returns_none(self):
        rule = make_rule(key="region", operator="eq", value="eu")
        config = make_gate_config(rules=[rule])

        result = FeatureGate.render_rules(config, {"region": "us"})
        assert result is None


class TestControl:

    def test_disabled_gate_bypasses_to_bandit(self):
        # a disabled gate does no gating: bandit selection proceeds
        committed = BaseArmModel(name="default", id="arm-0", index=0)
        config = make_gate_config(enabled=False, committed_arm=committed)

        result = FeatureGate.control(config, "ctx-1", {})
        assert result is None

    def test_disabled_gate_bypasses_even_outside_rollout_or_blackout(self):
        # disabled fully bypasses gating, even when blackout/rollout would commit
        committed = BaseArmModel(name="default", id="arm-0", index=0)
        config = make_gate_config(
            enabled=False, rollout_percentage=0.0, committed_arm=committed
        )
        with patch.object(
            type(config.experiment.schedule),
            "is_in_active_schedule",
            return_value=False,
        ):
            result = FeatureGate.control(config, "ctx-1", {})
        assert result is None

    def test_blackout_returns_committed_arm(self):
        committed = BaseArmModel(name="default", id="arm-0", index=0)
        config = make_gate_config(enabled=True, committed_arm=committed)
        with patch.object(
            type(config.experiment.schedule),
            "is_in_active_schedule",
            return_value=False,
        ):
            result = FeatureGate.control(config, "ctx-1", {})
        assert result == committed

    def test_rollout_negative_returns_committed(self):
        committed = BaseArmModel(name="default", id="arm-0", index=0)
        config = make_gate_config(
            enabled=True, rollout_percentage=0.0, committed_arm=committed
        )

        result = FeatureGate.control(config, "ctx-1", {})
        assert result == committed

    def test_matching_rule_returns_rule_arm(self):
        rule_arm = BaseArmModel(name="rule-winner", id="arm-r", index=1)
        rule = make_rule(
            key="region", operator="eq", value="us", committed_arm=rule_arm
        )
        config = make_gate_config(enabled=True, rollout_percentage=100.0, rules=[rule])

        result = FeatureGate.control(config, "ctx-1", {"region": "us"})
        assert result == rule_arm

    def test_no_match_returns_none(self):
        rule = make_rule(key="region", operator="eq", value="eu")
        config = make_gate_config(enabled=True, rollout_percentage=100.0, rules=[rule])

        result = FeatureGate.control(config, "ctx-1", {"region": "us"})
        assert result is None

    def test_partial_rollout_is_deterministic_for_same_identifier(self):
        # a partial rollout (0 < percentage < 100) is exactly the branch
        # that once bucketed per process — the same identifier must resolve the same way on
        # every call, not just at the 0%/100% boundaries the rest of this
        # suite exercises
        committed = BaseArmModel(name="default", id="arm-0", index=0)
        config = make_gate_config(
            enabled=True, rollout_percentage=50.0, committed_arm=committed
        )

        first = FeatureGate.control(config, "visitor-1", {})
        second = FeatureGate.control(config, "visitor-1", {})
        assert first == second


class TestRuleEvalOperators:
    """test Rule.eval() across all operator variants."""

    def _eval(self, operator, actual, expected):  # noqa
        from proxysvc.mod.gate.model.rule import Rule

        rule = Rule(key="x", operator=operator, value=expected)
        return rule.eval({"x": actual})

    # equality
    def test_equals(self):
        assert self._eval("equals", "a", "a") is True
        assert self._eval("==", "a", "b") is False

    def test_not_equals(self):
        assert self._eval("not_equals", "a", "b") is True
        assert self._eval("!=", "a", "a") is False
        assert self._eval("ne", 1, 2) is True

    # comparison
    def test_greater_than(self):
        assert self._eval("greater_than", 10, 5) is True
        assert self._eval(">", 5, 10) is False
        assert self._eval("gt", 5, 5) is False

    def test_less_than(self):
        assert self._eval("less_than", 3, 10) is True
        assert self._eval("<", 10, 3) is False
        assert self._eval("lt", 5, 5) is False

    def test_greater_or_equal(self):
        assert self._eval("greater_or_equal", 5, 5) is True
        assert self._eval(">=", 6, 5) is True
        assert self._eval("gte", 4, 5) is False

    def test_less_or_equal(self):
        assert self._eval("less_or_equal", 5, 5) is True
        assert self._eval("<=", 4, 5) is True
        assert self._eval("lte", 6, 5) is False

    # containment
    def test_contains(self):
        assert self._eval("contains", "hello world", "world") is True
        assert self._eval("contains", "hello", "xyz") is False
        assert self._eval("contains", [1, 2, 3], 2) is True

    def test_not_contains(self):
        assert self._eval("not_contains", "hello", "xyz") is True
        assert self._eval("not_contains", "hello", "ell") is False

    def test_in(self):
        assert self._eval("in", "us", ["us", "eu", "asia"]) is True
        assert self._eval("in", "br", ["us", "eu"]) is False

    def test_not_in(self):
        assert self._eval("not_in", "br", ["us", "eu"]) is True
        assert self._eval("not_in", "us", ["us", "eu"]) is False

    # edge cases
    def test_missing_key_returns_false(self):
        from proxysvc.mod.gate.model.rule import Rule

        rule = Rule(key="missing", operator="eq", value="x")
        assert rule.eval({"other": "y"}) is False

    def test_non_dict_metadata_returns_false(self):
        from proxysvc.mod.gate.model.rule import Rule

        rule = Rule(key="x", operator="eq", value="y")
        assert rule.eval("not a dict") is False  # noqa

    def test_type_error_returns_false(self):
        # comparing string > int should return False (TypeError caught)
        assert self._eval("gt", "abc", 5) is False
