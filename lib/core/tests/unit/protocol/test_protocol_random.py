"""Unit tests for RandomPolicy."""

import random

import numpy as np
import pytest

from qbrixcore.policy.rand import RandomPolicy
from qbrixcore.policy.rand import RandomParamState
from qbrixcore.context import Context


class TestRandomParamState:
    def test_param_state_creation_minimal(self):
        """test param state creation with only num_arms."""
        ps = RandomParamState(num_arms=3)

        assert ps.num_arms == 3

    def test_param_state_creation_with_single_arm(self):
        """test param state creation with single arm."""
        ps = RandomParamState(num_arms=1)

        assert ps.num_arms == 1

    def test_param_state_validation_num_arms_positive(self):
        """test param state validation requires positive num_arms."""
        with pytest.raises(ValueError):
            RandomParamState(num_arms=0)

        with pytest.raises(ValueError):
            RandomParamState(num_arms=-1)

    def test_param_state_id_is_unique(self):
        """test param state ids are unique."""
        ps1 = RandomParamState(num_arms=3)
        ps2 = RandomParamState(num_arms=3)

        assert ps1.id != ps2.id

    def test_param_state_has_no_learnable_fields(self):
        """test param state exposes only num_arms as a model field."""
        fields = RandomParamState.model_fields

        # only num_arms should be a declared field (no weights, counts, etc.)
        assert "num_arms" in fields
        assert len(fields) == 1


class TestRandomPolicy:
    def test_policy_name(self):
        """test policy has correct name."""
        assert RandomPolicy.name == "RandomPolicy"

    def test_policy_category(self):
        """test policy has correct category."""
        assert RandomPolicy.category == "stochastic"

    def test_policy_reward_types(self):
        """test policy accepts all reward types."""
        from qbrixcore.policy._reward_type import RewardType

        assert RewardType.BINARY in RandomPolicy.reward_types
        assert RewardType.BOUNDED in RandomPolicy.reward_types
        assert RewardType.CONTINUOUS in RandomPolicy.reward_types

    def test_policy_param_state_cls(self):
        """test policy has correct param state class."""
        assert RandomPolicy.param_state_cls == RandomParamState

    def test_init_params(self):
        """test init_params creates correct param state."""
        params = RandomPolicy.build_state(num_arms=4)

        assert isinstance(params, RandomParamState)
        assert params.num_arms == 4

    def test_select_returns_valid_arm_index(self):
        """test select returns valid arm index."""
        ps = RandomParamState(num_arms=5)
        ctx = Context()

        arm_index = RandomPolicy.select(ps, ctx)

        assert isinstance(arm_index, int)
        assert 0 <= arm_index < 5

    def test_select_single_arm_always_returns_zero(self):
        """test select with single arm always returns 0."""
        ps = RandomParamState(num_arms=1)
        ctx = Context()

        for _ in range(20):
            arm_index = RandomPolicy.select(ps, ctx)
            assert arm_index == 0

    def test_select_deterministic_with_seed(self):
        """test select is deterministic with fixed random seed."""
        ps = RandomParamState(num_arms=5)
        ctx = Context()

        random.seed(42)
        result1 = RandomPolicy.select(ps, ctx)

        random.seed(42)
        result2 = RandomPolicy.select(ps, ctx)

        assert result1 == result2

    def test_select_covers_all_arms(self):
        """test select samples all arms over many calls."""
        ps = RandomParamState(num_arms=4)
        ctx = Context()

        selections = [RandomPolicy.select(ps, ctx) for _ in range(200)]

        assert set(selections) == {0, 1, 2, 3}

    def test_select_approximately_uniform_distribution(self):
        """test select produces an approximately uniform distribution."""
        n_arms = 5
        n_samples = 5000
        ps = RandomParamState(num_arms=n_arms)
        ctx = Context()

        selections = [RandomPolicy.select(ps, ctx) for _ in range(n_samples)]

        expected_freq = n_samples / n_arms
        tolerance = 0.1 * expected_freq  # allow 10% deviation

        for arm in range(n_arms):
            count = selections.count(arm)
            assert (
                abs(count - expected_freq) < tolerance
            ), f"arm {arm} selected {count} times, expected ~{expected_freq}"

    def test_train_is_noop_returns_identical_state(self):
        """test train is a no-op and returns the exact same state object."""
        ps = RandomParamState(num_arms=3)
        ctx = Context()

        returned = RandomPolicy.train(ps, ctx, choice=1, reward=1.0)

        assert returned is ps

    def test_train_state_unchanged_after_success_reward(self):
        """test train does not change any state on success reward."""
        ps = RandomParamState(num_arms=3)
        ctx = Context()
        original_id = ps.id

        returned = RandomPolicy.train(ps, ctx, choice=0, reward=1)

        assert returned.id == original_id
        assert returned.num_arms == ps.num_arms

    def test_train_state_unchanged_after_failure_reward(self):
        """test train does not change any state on failure reward."""
        ps = RandomParamState(num_arms=3)
        ctx = Context()

        returned = RandomPolicy.train(ps, ctx, choice=2, reward=0)

        assert returned is ps

    def test_train_state_unchanged_after_continuous_reward(self):
        """test train does not change any state on continuous reward."""
        ps = RandomParamState(num_arms=3)
        ctx = Context()

        returned = RandomPolicy.train(ps, ctx, choice=1, reward=0.75)

        assert returned is ps

    def test_train_state_unchanged_with_numpy_reward(self):
        """test train handles numpy scalar reward as a no-op."""
        ps = RandomParamState(num_arms=3)
        ctx = Context()

        returned = RandomPolicy.train(ps, ctx, choice=0, reward=np.float64(1.0))

        assert returned is ps

    def test_train_does_not_learn_over_multiple_steps(self):
        """test select distribution is unaffected by prior rewards."""
        n_arms = 3
        n_samples = 1000
        ps = RandomParamState(num_arms=n_arms)
        ctx = Context()

        # train many times, always rewarding arm 0
        for _ in range(200):
            ps = RandomPolicy.train(ps, ctx, choice=0, reward=1)

        # distribution should still be uniform — policy does not learn
        selections = [RandomPolicy.select(ps, ctx) for _ in range(n_samples)]
        arm_0_count = selections.count(0)

        expected_freq = n_samples / n_arms
        tolerance = 0.15 * expected_freq
        assert abs(arm_0_count - expected_freq) < tolerance

    def test_user_params_returns_empty_list(self):
        """test user_params returns empty list because there are no configurable params."""
        params = RandomPolicy.user_params()

        assert params == []

    def test_integration_select_and_train_workflow(self):
        """test integration of repeated select/train cycles."""
        ps = RandomParamState(num_arms=4)
        ctx = Context()

        for _ in range(10):
            arm = RandomPolicy.select(ps, ctx)
            assert 0 <= arm < 4

            reward = random.random()
            ps = RandomPolicy.train(ps, ctx, choice=arm, reward=reward)

        # state should be exactly the same as initial (noop train)
        assert ps.num_arms == 4
