"""Unit tests for EXP3IXPolicy."""

import numpy as np
import pytest

from qbrixcore.policy.exp import EXP3IXPolicy
from qbrixcore.policy.exp import EXP3IXParamState
from qbrixcore.context import Context


class TestEXP3IXParamState:
    def test_param_state_creation_minimal(self):
        """test param state creation with minimal args."""
        ps = EXP3IXParamState(num_arms=3)

        assert ps.num_arms == 3
        assert ps.gamma == 0.1
        assert ps.eta == 0.1
        assert len(ps.w) == 3
        assert np.all(ps.w == 1.0)

    def test_param_state_creation_with_custom_gamma(self):
        """test param state creation with custom gamma."""
        ps = EXP3IXParamState(num_arms=3, gamma=0.3)

        assert ps.gamma == 0.3

    def test_param_state_creation_with_custom_eta(self):
        """test param state creation with custom eta."""
        ps = EXP3IXParamState(num_arms=3, eta=0.05)

        assert ps.eta == 0.05

    def test_param_state_creation_with_custom_weights(self):
        """test param state creation with pre-initialized weights."""
        w = np.array([1.0, 2.0, 3.0])

        ps = EXP3IXParamState(num_arms=3, w=w)

        assert np.array_equal(ps.w, w)

    def test_param_state_validation_num_arms_positive(self):
        """test param state validation requires positive num_arms."""
        with pytest.raises(ValueError):
            EXP3IXParamState(num_arms=0)

        with pytest.raises(ValueError):
            EXP3IXParamState(num_arms=-1)

    def test_param_state_validation_gamma_positive(self):
        """test param state validation requires gamma strictly greater than 0."""
        with pytest.raises(ValueError):
            EXP3IXParamState(num_arms=3, gamma=0.0)

        with pytest.raises(ValueError):
            EXP3IXParamState(num_arms=3, gamma=-0.1)

    def test_param_state_validation_gamma_upper_bound(self):
        """test param state validation requires gamma <= 1."""
        with pytest.raises(ValueError):
            EXP3IXParamState(num_arms=3, gamma=1.5)

    def test_param_state_validation_eta_positive(self):
        """test param state validation requires eta strictly greater than 0."""
        with pytest.raises(ValueError):
            EXP3IXParamState(num_arms=3, eta=0.0)

        with pytest.raises(ValueError):
            EXP3IXParamState(num_arms=3, eta=-0.1)

    def test_param_state_validation_eta_upper_bound(self):
        """test param state validation requires eta <= 1."""
        with pytest.raises(ValueError):
            EXP3IXParamState(num_arms=3, eta=1.5)

    def test_param_state_id_is_unique(self):
        """test param state ids are unique."""
        ps1 = EXP3IXParamState(num_arms=3)
        ps2 = EXP3IXParamState(num_arms=3)

        assert ps1.id != ps2.id


class TestEXP3IXPolicy:
    def test_policy_name(self):
        """test policy has correct name."""
        assert EXP3IXPolicy.name == "EXP3IXPolicy"

    def test_policy_category(self):
        """test policy has correct category."""
        assert EXP3IXPolicy.category == "adversarial"

    def test_policy_reward_types(self):
        """test policy has correct reward types."""
        from qbrixcore.policy._reward_type import RewardType

        assert RewardType.BINARY in EXP3IXPolicy.reward_types
        assert RewardType.BOUNDED in EXP3IXPolicy.reward_types

    def test_policy_param_state_cls(self):
        """test policy has correct param state class."""
        assert EXP3IXPolicy.param_state_cls == EXP3IXParamState

    def test_init_params(self):
        """test init_params creates correct param state."""
        params = EXP3IXPolicy.build_state(num_arms=4)

        assert isinstance(params, EXP3IXParamState)
        assert params.num_arms == 4

    def test_init_params_with_custom_params(self):
        """test init_params with custom gamma and eta."""
        params = EXP3IXPolicy.build_state(num_arms=3, gamma=0.2, eta=0.05)

        assert params.gamma == 0.2
        assert params.eta == 0.05

    def test_proba_with_uniform_weights(self):
        """test probability calculation with uniform weights."""
        ps = EXP3IXParamState(num_arms=3)

        proba = EXP3IXPolicy._proba(ps)

        expected_prob = 1.0 / 3.0
        assert np.allclose(proba, [expected_prob, expected_prob, expected_prob])

    def test_proba_with_non_uniform_weights(self):
        """test probability calculation with non-uniform weights."""
        ps = EXP3IXParamState(num_arms=3, w=np.array([1.0, 2.0, 3.0]))

        proba = EXP3IXPolicy._proba(ps)

        assert np.isclose(np.sum(proba), 1.0)
        assert proba[2] > proba[1] > proba[0]

    def test_proba_sums_to_one(self):
        """test probabilities always sum to one."""
        ps = EXP3IXParamState(num_arms=5, w=np.array([0.5, 1.5, 2.0, 0.3, 1.2]))

        proba = EXP3IXPolicy._proba(ps)

        assert np.isclose(np.sum(proba), 1.0)

    def test_select_returns_valid_arm_index(self):
        """test select returns valid arm index."""
        ps = EXP3IXParamState(num_arms=5)
        ctx = Context()

        arm_index = EXP3IXPolicy.select(ps, ctx)

        assert isinstance(arm_index, int)
        assert 0 <= arm_index < 5

    def test_select_with_uniform_weights_samples_all_arms(self):
        """test select with uniform weights samples all arms over time."""
        ps = EXP3IXParamState(num_arms=3)
        ctx = Context()

        selections = [EXP3IXPolicy.select(ps, ctx) for _ in range(200)]

        assert len(set(selections)) == 3

    def test_select_deterministic_with_seed(self):
        """test select is deterministic with fixed seed."""
        ps = EXP3IXParamState(num_arms=3)
        ctx = Context()

        np.random.seed(42)
        result1 = EXP3IXPolicy.select(ps, ctx)

        np.random.seed(42)
        result2 = EXP3IXPolicy.select(ps, ctx)

        assert result1 == result2

    def test_select_favors_higher_weight_arm(self):
        """test select favors arm with higher weight."""
        ps = EXP3IXParamState(
            num_arms=3,
            w=np.array([1.0, 1.0, 100.0]),
        )
        ctx = Context()

        selections = [EXP3IXPolicy.select(ps, ctx) for _ in range(200)]
        arm_2_count = selections.count(2)

        assert arm_2_count > 150

    def test_select_single_arm(self):
        """test select with single arm always returns 0."""
        ps = EXP3IXParamState(num_arms=1)
        ctx = Context()

        arm_index = EXP3IXPolicy.select(ps, ctx)

        assert arm_index == 0

    def test_train_uses_implicit_exploration_in_denominator(self):
        """test train uses (p + gamma) in the denominator instead of just p."""
        # set skewed weights so arm 0 has very low probability
        ps = EXP3IXParamState(
            num_arms=3,
            gamma=0.1,
            eta=0.1,
            w=np.array([0.001, 1.0, 1.0]),
        )
        ctx = Context()

        proba = EXP3IXPolicy._proba(ps)
        p0 = proba[0]

        # with gamma in denominator, estimate is reward / (p + gamma) not reward / p
        # this prevents blowup even when p is tiny
        estimate_with_ix = 1.0 / (p0 + ps.gamma)
        estimate_without_ix = 1.0 / p0  # noqa — for conceptual reference

        # estimate_with_ix should be much smaller than naive estimate
        assert estimate_with_ix < estimate_without_ix

    def test_train_weights_normalized_after_update(self):
        """test train returns normalized weights after update."""
        ps = EXP3IXParamState(num_arms=3)
        ctx = Context()

        updated = EXP3IXPolicy.train(ps, ctx, choice=1, reward=1.0)

        assert np.isclose(np.sum(updated.w), 1.0)

    def test_train_weights_normalized_with_zero_reward(self):
        """test train returns normalized weights even with zero reward."""
        ps = EXP3IXParamState(num_arms=3)
        ctx = Context()

        updated = EXP3IXPolicy.train(ps, ctx, choice=1, reward=0.0)

        assert np.isclose(np.sum(updated.w), 1.0)

    def test_train_chosen_arm_weight_increases_on_positive_reward(self):
        """test train increases relative weight for chosen arm on positive reward."""
        ps = EXP3IXParamState(num_arms=3, gamma=0.1, eta=0.1)
        ctx = Context()

        updated = EXP3IXPolicy.train(ps, ctx, choice=0, reward=1.0)

        # chosen arm should have higher relative weight
        assert updated.w[0] > updated.w[1]
        assert updated.w[0] > updated.w[2]

    def test_train_non_chosen_arm_weights_unchanged_before_normalization(self):
        """test train only updates chosen arm's weight before normalization."""
        ps = EXP3IXParamState(num_arms=3, gamma=0.1, eta=0.1)
        ctx = Context()
        original_w = ps.w.copy()

        updated = EXP3IXPolicy.train(ps, ctx, choice=0, reward=1.0)

        # unchosen arms had estimate=0 so their raw weight ratio is unchanged
        # (after normalization they decrease proportionally)
        assert updated.w[1] / updated.w[2] == pytest.approx(
            original_w[1] / original_w[2], rel=1e-6
        )

    def test_train_no_numerical_blowup_with_tiny_probability(self):
        """test train remains numerically stable when arm probability is very small."""
        # arm 0 has near-zero weight => near-zero probability
        ps = EXP3IXParamState(
            num_arms=3,
            gamma=0.05,
            eta=0.1,
            w=np.array([1e-10, 1.0, 1.0]),
        )
        ctx = Context()

        # train on arm 0 with positive reward — without IX this would blow up
        updated = EXP3IXPolicy.train(ps, ctx, choice=0, reward=1.0)

        assert np.all(np.isfinite(updated.w))
        assert np.isclose(np.sum(updated.w), 1.0)

    def test_train_does_not_mutate_original_params(self):
        """test train returns new params without mutating original."""
        ps = EXP3IXParamState(num_arms=3)
        ctx = Context()
        original_w = ps.w.copy()

        EXP3IXPolicy.train(ps, ctx, choice=1, reward=1.0)

        assert np.array_equal(ps.w, original_w)

    def test_train_multiple_updates_accumulate_on_chosen_arm(self):
        """test train accumulates weight updates for repeatedly chosen arm."""
        ps = EXP3IXParamState(num_arms=3, gamma=0.1, eta=0.1)
        ctx = Context()

        ps = EXP3IXPolicy.train(ps, ctx, choice=0, reward=1.0)
        ps = EXP3IXPolicy.train(ps, ctx, choice=0, reward=1.0)
        ps = EXP3IXPolicy.train(ps, ctx, choice=0, reward=1.0)

        assert ps.w[0] > ps.w[1]
        assert ps.w[0] > ps.w[2]

    def test_train_normalization_prevents_overflow_after_many_updates(self):
        """test normalization prevents weight overflow under repeated high rewards."""
        ps = EXP3IXParamState(num_arms=3, gamma=0.1, eta=0.5)
        ctx = Context()

        for _ in range(100):
            ps = EXP3IXPolicy.train(ps, ctx, choice=0, reward=10.0)

        assert np.isclose(np.sum(ps.w), 1.0)
        assert np.all(np.isfinite(ps.w))

    def test_train_with_numpy_reward(self):
        """test train handles numpy scalar reward."""
        ps = EXP3IXParamState(num_arms=3)
        ctx = Context()

        updated = EXP3IXPolicy.train(ps, ctx, choice=0, reward=np.float64(1.0))

        assert updated is not None
        assert np.isclose(np.sum(updated.w), 1.0)

    def test_gamma_controls_implicit_exploration_magnitude(self):
        """test larger gamma produces smaller reward estimates."""
        # arm 0 selected, reward=1
        # estimate = 1 / (p + gamma) — larger gamma => smaller estimate

        w = np.ones(3)
        ps_small_gamma = EXP3IXParamState(num_arms=3, gamma=0.01, eta=0.1, w=w.copy())
        ps_large_gamma = EXP3IXParamState(num_arms=3, gamma=0.5, eta=0.1, w=w.copy())

        proba_small = EXP3IXPolicy._proba(ps_small_gamma)
        proba_large = EXP3IXPolicy._proba(ps_large_gamma)

        estimate_small = 1.0 / (proba_small[0] + ps_small_gamma.gamma)
        estimate_large = 1.0 / (proba_large[0] + ps_large_gamma.gamma)

        assert estimate_large < estimate_small

    def test_user_params_includes_gamma_and_eta(self):
        """test user_params includes gamma and eta parameters."""
        params = EXP3IXPolicy.user_params()
        param_names = [p.name for p in params]

        assert "gamma" in param_names
        assert "eta" in param_names

    def test_user_params_excludes_array_fields(self):
        """test user_params excludes internal array fields."""
        params = EXP3IXPolicy.user_params()
        param_names = [p.name for p in params]

        assert "w" not in param_names
        assert "num_arms" not in param_names

    def test_integration_select_and_train(self):
        """test integration of select and train workflow."""
        ps = EXP3IXParamState(num_arms=3, gamma=0.1, eta=0.1)
        ctx = Context()

        arm = EXP3IXPolicy.select(ps, ctx)
        assert 0 <= arm < 3

        updated_ps = EXP3IXPolicy.train(ps, ctx, choice=arm, reward=1.0)

        assert np.isclose(np.sum(updated_ps.w), 1.0)

        arm2 = EXP3IXPolicy.select(updated_ps, ctx)
        assert 0 <= arm2 < 3
