"""Unit tests for DiscountedTSPolicy."""

import numpy as np
import pytest

from qbrixcore.policy.ts import DiscountedTSPolicy
from qbrixcore.policy.ts import DiscountedTSParamState
from qbrixcore.context import Context


class TestDiscountedTSParamState:
    def test_param_state_creation_with_required_gamma(self):
        """test param state creation requires gamma."""
        ps = DiscountedTSParamState(num_arms=3, gamma=0.99)

        assert ps.num_arms == 3
        assert ps.gamma == 0.99
        assert ps.alpha_prior == 1.0
        assert ps.beta_prior == 1.0
        assert len(ps.alpha) == 3
        assert len(ps.beta) == 3
        assert len(ps.T) == 3
        assert np.all(ps.alpha == 1.0)
        assert np.all(ps.beta == 1.0)
        assert np.all(ps.T == 0)

    def test_param_state_creation_requires_gamma(self):
        """test param state creation fails without gamma."""
        with pytest.raises((ValueError, TypeError)):
            DiscountedTSParamState(num_arms=3)

    def test_param_state_creation_with_custom_priors(self):
        """test param state creation with custom priors."""
        ps = DiscountedTSParamState(
            num_arms=3, gamma=0.95, alpha_prior=2.0, beta_prior=3.0
        )

        assert ps.alpha_prior == 2.0
        assert ps.beta_prior == 3.0
        assert np.all(ps.alpha == 2.0)
        assert np.all(ps.beta == 3.0)

    def test_param_state_creation_with_custom_arrays(self):
        """test param state creation with pre-initialized arrays."""
        alpha = np.array([2.0, 3.0, 4.0])
        beta = np.array([1.0, 2.0, 3.0])
        T = np.array([10, 20, 30])

        ps = DiscountedTSParamState(num_arms=3, gamma=0.99, alpha=alpha, beta=beta, T=T)

        assert np.array_equal(ps.alpha, alpha)
        assert np.array_equal(ps.beta, beta)
        assert np.array_equal(ps.T, T)

    def test_param_state_validation_num_arms_positive(self):
        """test param state validation requires positive num_arms."""
        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=0, gamma=0.99)

        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=-1, gamma=0.99)

    def test_param_state_validation_alpha_prior_positive(self):
        """test param state validation requires positive alpha_prior."""
        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=3, gamma=0.99, alpha_prior=0.0)

        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=3, gamma=0.99, alpha_prior=-1.0)

    def test_param_state_validation_beta_prior_positive(self):
        """test param state validation requires positive beta_prior."""
        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=3, gamma=0.99, beta_prior=0.0)

        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=3, gamma=0.99, beta_prior=-1.0)

    def test_param_state_validation_gamma_bounds(self):
        """test param state validation requires gamma strictly between 0 and 1."""
        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=3, gamma=0.0)

        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=3, gamma=1.0)

        with pytest.raises(ValueError):
            DiscountedTSParamState(num_arms=3, gamma=1.5)

    def test_param_state_id_is_unique(self):
        """test param state ids are unique."""
        ps1 = DiscountedTSParamState(num_arms=3, gamma=0.99)
        ps2 = DiscountedTSParamState(num_arms=3, gamma=0.99)

        assert ps1.id != ps2.id


class TestDiscountedTSPolicy:
    def test_policy_name(self):
        """test policy has correct name."""
        assert DiscountedTSPolicy.name == "DiscountedTSPolicy"

    def test_policy_category(self):
        """test policy has correct category."""
        assert DiscountedTSPolicy.category == "stochastic"

    def test_policy_reward_types(self):
        """test policy has correct reward types."""
        from qbrixcore.policy._reward_type import RewardType

        assert RewardType.BINARY in DiscountedTSPolicy.reward_types
        assert RewardType.BOUNDED in DiscountedTSPolicy.reward_types

    def test_policy_param_state_cls(self):
        """test policy has correct param state class."""
        assert DiscountedTSPolicy.param_state_cls == DiscountedTSParamState

    def test_init_params(self):
        """test init_params creates correct param state."""
        params = DiscountedTSPolicy.build_state(num_arms=4, gamma=0.99)

        assert isinstance(params, DiscountedTSParamState)
        assert params.num_arms == 4
        assert params.gamma == 0.99

    def test_init_params_with_custom_priors(self):
        """test init_params with custom priors."""
        params = DiscountedTSPolicy.build_state(
            num_arms=3,
            gamma=0.95,
            alpha_prior=2.0,
            beta_prior=3.0,
        )

        assert params.alpha_prior == 2.0
        assert params.beta_prior == 3.0

    def test_select_returns_valid_arm_index(self):
        """test select returns valid arm index."""
        ps = DiscountedTSParamState(num_arms=5, gamma=0.99)
        ctx = Context()

        arm_index = DiscountedTSPolicy.select(ps, ctx)

        assert isinstance(arm_index, int)
        assert 0 <= arm_index < 5

    def test_select_with_skewed_params(self):
        """test select with non-uniform params favors better arm."""
        # arm 0 has high success rate
        ps = DiscountedTSParamState(
            num_arms=3,
            gamma=0.99,
            alpha=np.array([100.0, 2.0, 2.0]),
            beta=np.array([2.0, 100.0, 100.0]),
        )
        ctx = Context()

        selections = [DiscountedTSPolicy.select(ps, ctx) for _ in range(100)]
        arm_0_count = selections.count(0)

        assert arm_0_count > 50

    def test_select_deterministic_with_seed(self):
        """test select is deterministic with fixed seed."""
        ps = DiscountedTSParamState(num_arms=3, gamma=0.99)
        ctx = Context()

        np.random.seed(42)
        result1 = DiscountedTSPolicy.select(ps, ctx)

        np.random.seed(42)
        result2 = DiscountedTSPolicy.select(ps, ctx)

        assert result1 == result2

    def test_select_single_arm(self):
        """test select with single arm always returns 0."""
        ps = DiscountedTSParamState(num_arms=1, gamma=0.99)
        ctx = Context()

        arm_index = DiscountedTSPolicy.select(ps, ctx)

        assert arm_index == 0

    def test_train_discounts_all_arms_before_update(self):
        """test train applies gamma discount to all arms on every step."""
        gamma = 0.9
        ps = DiscountedTSParamState(
            num_arms=3,
            gamma=gamma,
            alpha=np.array([2.0, 4.0, 6.0]),
            beta=np.array([1.0, 2.0, 3.0]),
        )
        ctx = Context()

        updated = DiscountedTSPolicy.train(ps, ctx, choice=0, reward=1)

        # unchosen arms: only discounted, no observation added
        assert updated.alpha[1] == pytest.approx(4.0 * gamma)
        assert updated.beta[1] == pytest.approx(2.0 * gamma)
        assert updated.alpha[2] == pytest.approx(6.0 * gamma)
        assert updated.beta[2] == pytest.approx(3.0 * gamma)

    def test_train_chosen_arm_discounted_then_incremented_on_success(self):
        """test chosen arm is discounted then gets alpha incremented for success."""
        gamma = 0.9
        ps = DiscountedTSParamState(
            num_arms=3,
            gamma=gamma,
            alpha=np.array([2.0, 1.0, 1.0]),
            beta=np.array([1.0, 1.0, 1.0]),
        )
        ctx = Context()

        updated = DiscountedTSPolicy.train(ps, ctx, choice=0, reward=1)

        # chosen arm: discounted alpha + 1 (success)
        assert updated.alpha[0] == pytest.approx(2.0 * gamma + 1.0)
        # chosen arm: discounted beta only (no failure)
        assert updated.beta[0] == pytest.approx(1.0 * gamma)

    def test_train_chosen_arm_discounted_then_incremented_on_failure(self):
        """test chosen arm is discounted then gets beta incremented for failure."""
        gamma = 0.9
        ps = DiscountedTSParamState(
            num_arms=3,
            gamma=gamma,
            alpha=np.array([2.0, 1.0, 1.0]),
            beta=np.array([3.0, 1.0, 1.0]),
        )
        ctx = Context()

        updated = DiscountedTSPolicy.train(ps, ctx, choice=0, reward=0)

        # chosen arm: discounted alpha only (no success)
        assert updated.alpha[0] == pytest.approx(2.0 * gamma)
        # chosen arm: discounted beta + 1 (failure)
        assert updated.beta[0] == pytest.approx(3.0 * gamma + 1.0)

    def test_train_with_continuous_reward_above_threshold(self):
        """test train converts continuous reward > 0.5 to success."""
        ps = DiscountedTSParamState(num_arms=3, gamma=0.99)
        ctx = Context()

        updated = DiscountedTSPolicy.train(ps, ctx, choice=0, reward=0.8)

        # alpha should increase for choice (0.99 * 1.0 + 1.0 = 1.99)
        assert updated.alpha[0] == pytest.approx(0.99 * 1.0 + 1.0)
        assert updated.beta[0] == pytest.approx(0.99 * 1.0)

    def test_train_with_continuous_reward_below_threshold(self):
        """test train converts continuous reward <= 0.5 to failure."""
        ps = DiscountedTSParamState(num_arms=3, gamma=0.99)
        ctx = Context()

        updated = DiscountedTSPolicy.train(ps, ctx, choice=0, reward=0.3)

        assert updated.alpha[0] == pytest.approx(0.99 * 1.0)
        assert updated.beta[0] == pytest.approx(0.99 * 1.0 + 1.0)

    def test_train_increments_T_for_chosen_arm(self):
        """test train increments trial counter for chosen arm only."""
        ps = DiscountedTSParamState(num_arms=3, gamma=0.99)
        ctx = Context()

        updated = DiscountedTSPolicy.train(ps, ctx, choice=2, reward=1)

        assert updated.T[2] == 1
        assert updated.T[0] == 0
        assert updated.T[1] == 0

    def test_train_does_not_mutate_original_params(self):
        """test train returns new params without mutating original."""
        ps = DiscountedTSParamState(num_arms=3, gamma=0.99)
        ctx = Context()
        original_alpha = ps.alpha.copy()
        original_beta = ps.beta.copy()
        original_T = ps.T.copy()

        DiscountedTSPolicy.train(ps, ctx, choice=1, reward=1)

        assert np.array_equal(ps.alpha, original_alpha)
        assert np.array_equal(ps.beta, original_beta)
        assert np.array_equal(ps.T, original_T)

    def test_train_with_numpy_reward(self):
        """test train handles numpy scalar reward."""
        ps = DiscountedTSParamState(num_arms=3, gamma=0.99)
        ctx = Context()

        updated = DiscountedTSPolicy.train(ps, ctx, choice=0, reward=np.float64(1.0))

        assert updated.alpha[0] == pytest.approx(0.99 * 1.0 + 1.0)

    def test_train_repeated_discounting_fades_old_observations(self):
        """test repeated discount steps exponentially decay old counts."""
        gamma = 0.5
        ps = DiscountedTSParamState(
            num_arms=2,
            gamma=gamma,
            alpha=np.array([10.0, 1.0]),
            beta=np.array([1.0, 1.0]),
        )
        ctx = Context()

        # apply many discount steps by training on arm 1 with zero reward
        for _ in range(20):
            ps = DiscountedTSPolicy.train(ps, ctx, choice=1, reward=0)

        # arm 0's alpha should have decayed toward zero
        assert ps.alpha[0] < 1.0

    def test_user_params_includes_gamma(self):
        """test user_params includes gamma as a required parameter."""
        params = DiscountedTSPolicy.user_params()
        param_names = [p.name for p in params]

        assert "gamma" in param_names

        gamma_param = next(p for p in params if p.name == "gamma")
        assert gamma_param.required is True
        assert gamma_param.default is None

    def test_user_params_includes_priors(self):
        """test user_params includes alpha_prior and beta_prior."""
        params = DiscountedTSPolicy.user_params()
        param_names = [p.name for p in params]

        assert "alpha_prior" in param_names
        assert "beta_prior" in param_names

    def test_user_params_excludes_array_fields(self):
        """test user_params excludes internal array fields."""
        params = DiscountedTSPolicy.user_params()
        param_names = [p.name for p in params]

        assert "alpha" not in param_names
        assert "beta" not in param_names
        assert "T" not in param_names
        assert "num_arms" not in param_names

    def test_integration_select_and_train(self):
        """test integration of select and train workflow."""
        ps = DiscountedTSParamState(num_arms=3, gamma=0.95)
        ctx = Context()

        arm = DiscountedTSPolicy.select(ps, ctx)
        assert 0 <= arm < 3

        updated_ps = DiscountedTSPolicy.train(ps, ctx, choice=arm, reward=1)

        # all alpha/beta should have been discounted
        for i in range(3):
            assert updated_ps.alpha[i] <= ps.alpha[i] + 1.0
            assert updated_ps.beta[i] <= ps.beta[i] + 1.0

        arm2 = DiscountedTSPolicy.select(updated_ps, ctx)
        assert 0 <= arm2 < 3
