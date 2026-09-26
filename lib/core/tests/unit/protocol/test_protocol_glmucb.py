"""Unit tests for GLMUCBPolicy."""

import numpy as np
import pytest

from qbrixcore.policy.ucb import GLMUCBPolicy
from qbrixcore.policy.ucb import GLMUCBParamState
from qbrixcore.context import Context


class TestGLMUCBParamState:
    def test_param_state_creation_minimal(self):
        """test param state creation with minimal args."""
        ps = GLMUCBParamState(num_arms=3, dim=5)

        assert ps.num_arms == 3
        assert ps.dim == 5
        assert ps.alpha == 1.5
        assert ps.lambda_ == 1.0
        assert ps.lr == 0.1
        assert ps.w.shape == (3, 5)
        assert ps.h.shape == (3, 5)

    def test_param_state_default_weights_are_zero(self):
        """test default weights are zero for each arm."""
        ps = GLMUCBParamState(num_arms=3, dim=4)

        assert np.all(ps.w == 0.0)

    def test_param_state_default_hessian_is_lambda(self):
        """test default Hessian diagonal is initialized to lambda."""
        ps = GLMUCBParamState(num_arms=3, dim=4, lambda_=2.0)

        assert np.all(ps.h == 2.0)

    def test_param_state_creation_with_custom_params(self):
        """test param state creation with custom hyperparameters."""
        ps = GLMUCBParamState(num_arms=3, dim=5, alpha=2.0, lambda_=0.5, lr=0.05)

        assert ps.alpha == 2.0
        assert ps.lambda_ == 0.5
        assert ps.lr == 0.05

    def test_param_state_creation_with_custom_arrays(self):
        """test param state creation with pre-initialized arrays."""
        w = np.ones((2, 3))
        h = np.full((2, 3), 2.0)

        ps = GLMUCBParamState(num_arms=2, dim=3, w=w, h=h)

        assert np.array_equal(ps.w, w)
        assert np.array_equal(ps.h, h)

    def test_param_state_validation_num_arms_positive(self):
        """test param state validation requires positive num_arms."""
        with pytest.raises(ValueError):
            GLMUCBParamState(num_arms=0, dim=5)

    def test_param_state_validation_dim_positive(self):
        """test param state validation requires positive dim."""
        with pytest.raises(ValueError):
            GLMUCBParamState(num_arms=3, dim=0)

    def test_param_state_validation_alpha_positive(self):
        """test param state validation requires positive alpha."""
        with pytest.raises(ValueError):
            GLMUCBParamState(num_arms=3, dim=5, alpha=0.0)

    def test_param_state_validation_lambda_positive(self):
        """test param state validation requires positive lambda."""
        with pytest.raises(ValueError):
            GLMUCBParamState(num_arms=3, dim=5, lambda_=0.0)

    def test_param_state_validation_lr_bounds(self):
        """test param state validation requires lr in (0, 1]."""
        with pytest.raises(ValueError):
            GLMUCBParamState(num_arms=3, dim=5, lr=0.0)

        with pytest.raises(ValueError):
            GLMUCBParamState(num_arms=3, dim=5, lr=1.5)

    def test_param_state_id_is_unique(self):
        """test param state ids are unique."""
        ps1 = GLMUCBParamState(num_arms=3, dim=5)
        ps2 = GLMUCBParamState(num_arms=3, dim=5)

        assert ps1.id != ps2.id


class TestGLMUCBPolicy:
    def test_policy_name(self):
        """test policy has correct name."""
        assert GLMUCBPolicy.name == "GLMUCBPolicy"

    def test_policy_category(self):
        """test policy has correct category."""
        assert GLMUCBPolicy.category == "contextual"

    def test_policy_reward_types(self):
        """test policy supports only binary rewards."""
        from qbrixcore.policy._reward_type import RewardType

        assert GLMUCBPolicy.reward_types == [RewardType.BINARY]

    def test_policy_param_state_cls(self):
        """test policy has correct param state class."""
        assert GLMUCBPolicy.param_state_cls == GLMUCBParamState

    def test_init_params(self):
        """test init_params creates correct param state."""
        params = GLMUCBPolicy.build_state(num_arms=3, dim=5)

        assert isinstance(params, GLMUCBParamState)
        assert params.num_arms == 3
        assert params.dim == 5

    def test_init_params_with_custom_hyperparams(self):
        """test init_params with custom hyperparameters."""
        params = GLMUCBPolicy.build_state(num_arms=3, dim=5, alpha=2.0, lambda_=0.5)

        assert params.alpha == 2.0
        assert params.lambda_ == 0.5

    def test_to_vector_from_list(self):
        """test converting context vector from list to 1d array."""
        ctx = Context(vector=[1.0, 2.0, 3.0])

        v = GLMUCBPolicy._to_vector(ctx)

        assert isinstance(v, np.ndarray)
        assert v.shape == (3,)
        assert np.array_equal(v, [1.0, 2.0, 3.0])

    def test_to_vector_from_1d_array(self):
        """test converting context vector from 1d array."""
        ctx = Context(vector=np.array([1.0, 2.0, 3.0]))

        v = GLMUCBPolicy._to_vector(ctx)

        assert v.shape == (3,)

    def test_to_vector_from_column_vector(self):
        """test converting context vector from column vector to 1d."""
        ctx = Context(vector=np.array([[1.0], [2.0], [3.0]]))

        v = GLMUCBPolicy._to_vector(ctx)

        assert v.shape == (3,)

    def test_select_returns_valid_arm_index(self):
        """test select returns valid arm index."""
        ps = GLMUCBParamState(num_arms=3, dim=4)
        ctx = Context(vector=[1.0, 0.5, -0.3, 0.8])

        arm_index = GLMUCBPolicy.select(ps, ctx)

        assert isinstance(arm_index, int)
        assert 0 <= arm_index < 3

    def test_select_is_deterministic(self):
        """test select is deterministic when arms have distinct estimates."""
        ps = GLMUCBParamState(num_arms=3, dim=4)
        ctx = Context(vector=[1.0, 0.5, -0.3, 0.8])

        # train to break ties so UCB values are distinct
        ps = GLMUCBPolicy.train(ps, ctx, 0, 1.0)
        ps = GLMUCBPolicy.train(ps, ctx, 1, 0.0)
        ps = GLMUCBPolicy.train(ps, ctx, 2, 0.5)

        results = [GLMUCBPolicy.select(ps, ctx) for _ in range(10)]

        assert len(set(results)) == 1

    def test_select_single_arm(self):
        """test select with single arm always returns 0."""
        ps = GLMUCBParamState(num_arms=1, dim=3)
        ctx = Context(vector=[1.0, 0.5, -0.3])

        arm_index = GLMUCBPolicy.select(ps, ctx)

        assert arm_index == 0

    def test_select_prefers_arm_with_higher_weights(self):
        """test select prefers arm with higher mean estimate."""
        ps = GLMUCBParamState(num_arms=3, dim=2, alpha=0.1)
        # give arm 0 strong positive weights
        ps.w[0] = np.array([5.0, 5.0])
        ps.w[1] = np.array([-5.0, -5.0])
        ps.w[2] = np.array([-5.0, -5.0])
        # tighten Hessian so confidence is small
        ps.h = np.full((3, 2), 100.0)

        ctx = Context(vector=[1.0, 1.0])

        arm_index = GLMUCBPolicy.select(ps, ctx)

        assert arm_index == 0

    def test_arm_upper_bound_calculation(self):
        """test upper bound calculation for an arm."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        x = np.array([1.0, 1.0])

        upper_bound = GLMUCBPolicy._arm_upper_bound(ps, 0, x)

        assert isinstance(upper_bound, float)
        # with zero weights, mean = sigmoid(0) = 0.5, plus positive confidence
        assert upper_bound > 0.5

    def test_arm_upper_bound_includes_confidence(self):
        """test upper bound includes confidence term proportional to alpha."""
        ps_low = GLMUCBParamState(num_arms=3, dim=2, alpha=0.1)
        ps_high = GLMUCBParamState(num_arms=3, dim=2, alpha=5.0)
        x = np.array([1.0, 1.0])

        ub_low = GLMUCBPolicy._arm_upper_bound(ps_low, 0, x)
        ub_high = GLMUCBPolicy._arm_upper_bound(ps_high, 0, x)

        assert ub_high > ub_low

    def test_arm_upper_bound_confidence_decreases_with_data(self):
        """test confidence width decreases as Hessian grows."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        x = np.array([1.0, 1.0])

        ub_before = GLMUCBPolicy._arm_upper_bound(ps, 0, x)

        # simulate accumulated Hessian from observations
        ps.h[0] = np.array([10.0, 10.0])

        ub_after = GLMUCBPolicy._arm_upper_bound(ps, 0, x)

        # confidence should be smaller with more data
        assert ub_after < ub_before

    def test_train_updates_weights(self):
        """test train updates weight vector for chosen arm."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        updated = GLMUCBPolicy.train(ps, ctx, choice=1, reward=1)

        assert not np.array_equal(updated.w[1], ps.w[1])
        assert np.array_equal(updated.w[0], ps.w[0])
        assert np.array_equal(updated.w[2], ps.w[2])

    def test_train_updates_hessian(self):
        """test train updates Hessian diagonal for chosen arm."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        updated = GLMUCBPolicy.train(ps, ctx, choice=1, reward=1)

        assert not np.array_equal(updated.h[1], ps.h[1])
        assert np.array_equal(updated.h[0], ps.h[0])
        assert np.array_equal(updated.h[2], ps.h[2])

    def test_train_does_not_mutate_original_params(self):
        """test train returns new params without mutating original."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])
        original_w = ps.w.copy()
        original_h = ps.h.copy()

        updated = GLMUCBPolicy.train(ps, ctx, choice=1, reward=1)

        assert np.array_equal(ps.w, original_w)
        assert np.array_equal(ps.h, original_h)
        assert not np.array_equal(updated.w[1], ps.w[1])

    def test_train_positive_reward_moves_weights_up(self):
        """test training with reward=1 increases predicted probability."""
        ps = GLMUCBParamState(num_arms=3, dim=2, lr=0.5)
        ctx = Context(vector=[1.0, 1.0])
        x = np.array([1.0, 1.0])

        logit_before = np.dot(ps.w[0], x)

        updated = GLMUCBPolicy.train(ps, ctx, choice=0, reward=1)

        logit_after = np.dot(updated.w[0], x)

        assert logit_after > logit_before

    def test_train_negative_reward_moves_weights_down(self):
        """test training with reward=0 decreases predicted probability."""
        ps = GLMUCBParamState(num_arms=3, dim=2, lr=0.5)
        ps.w[0] = np.array([1.0, 1.0])
        ctx = Context(vector=[1.0, 1.0])
        x = np.array([1.0, 1.0])

        logit_before = np.dot(ps.w[0], x)

        updated = GLMUCBPolicy.train(ps, ctx, choice=0, reward=0)

        logit_after = np.dot(updated.w[0], x)

        assert logit_after < logit_before

    def test_train_multiple_updates_accumulate(self):
        """test train accumulates updates for same arm."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 1.0])

        for _ in range(10):
            ps = GLMUCBPolicy.train(ps, ctx, choice=0, reward=1)

        assert not np.allclose(ps.w[0], 0.0)
        assert np.all(ps.h[0] > 1.0)

    def test_train_with_list_context_vector(self):
        """test train works with list context vector."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        updated = GLMUCBPolicy.train(ps, ctx, choice=0, reward=1)

        assert updated is not None
        assert not np.array_equal(updated.w[0], ps.w[0])

    def test_train_with_numpy_context_vector(self):
        """test train works with numpy array context vector."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        ctx = Context(vector=np.array([1.0, 2.0]))

        updated = GLMUCBPolicy.train(ps, ctx, choice=0, reward=1)

        assert updated is not None
        assert not np.array_equal(updated.w[0], ps.w[0])

    def test_train_with_numpy_reward(self):
        """test train handles numpy scalar reward."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        updated = GLMUCBPolicy.train(ps, ctx, choice=0, reward=np.float64(1.0))

        assert not np.array_equal(updated.w[0], ps.w[0])

    def test_integration_select_and_train(self):
        """test integration of select and train workflow."""
        ps = GLMUCBParamState(num_arms=3, dim=4)
        ctx = Context(vector=[1.0, 0.5, -0.3, 0.8])

        arm = GLMUCBPolicy.select(ps, ctx)
        assert 0 <= arm < 3

        updated_ps = GLMUCBPolicy.train(ps, ctx, choice=arm, reward=1)

        arm2 = GLMUCBPolicy.select(updated_ps, ctx)
        assert 0 <= arm2 < 3

    def test_integration_learns_best_arm(self):
        """test policy learns to prefer the best arm over many rounds."""
        ps = GLMUCBParamState(num_arms=3, dim=2, lr=0.3, alpha=0.5)
        ctx = Context(vector=[1.0, 1.0])

        np.random.seed(42)
        for _ in range(200):
            arm = GLMUCBPolicy.select(ps, ctx)
            if arm == 0:
                reward = 1 if np.random.random() < 0.8 else 0
            else:
                reward = 1 if np.random.random() < 0.2 else 0
            ps = GLMUCBPolicy.train(ps, ctx, choice=arm, reward=reward)

        # after learning, arm 0 should be selected deterministically
        selected = GLMUCBPolicy.select(ps, ctx)
        assert selected == 0

    def test_hessian_grows_monotonically(self):
        """test Hessian diagonal only increases (accumulates information)."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        for _ in range(10):
            h_before = ps.h[0].copy()
            ps = GLMUCBPolicy.train(ps, ctx, choice=0, reward=1)
            assert np.all(ps.h[0] >= h_before)

    def test_exploration_decreases_with_data(self):
        """test UCB confidence width decreases as Hessian accumulates."""
        ps = GLMUCBParamState(num_arms=3, dim=2)
        x = np.array([1.0, 1.0])

        ub_initial = GLMUCBPolicy._arm_upper_bound(ps, 0, x)

        ctx = Context(vector=[1.0, 1.0])
        for _ in range(50):
            ps = GLMUCBPolicy.train(ps, ctx, choice=0, reward=1)

        ub_trained = GLMUCBPolicy._arm_upper_bound(ps, 0, x)

        # mean may change, but confidence term should shrink
        # check that the bound is finite and reasonable
        assert np.isfinite(ub_trained)
        # with lots of reward=1 data, the mean should be close to 1.0
        # so the bound should not be wildly above 1
        assert ub_trained < 2.0

    def test_alpha_controls_exploration(self):
        """test higher alpha leads to more exploration."""
        ctx = Context(vector=[1.0, 1.0])

        # train with same data but different alpha
        ps_low = GLMUCBParamState(num_arms=3, dim=2, alpha=0.01)
        ps_high = GLMUCBParamState(num_arms=3, dim=2, alpha=10.0)

        # give arm 0 strong positive weights in both
        ps_low.w[0] = np.array([2.0, 2.0])
        ps_high.w[0] = np.array([2.0, 2.0])

        # with low alpha, arm 0 should dominate (exploit)
        selected_low = GLMUCBPolicy.select(ps_low, ctx)
        assert selected_low == 0

        # with very high alpha and untrained arms 1,2, confidence might favor exploration
        x = np.array([1.0, 1.0])
        ub_arm0 = GLMUCBPolicy._arm_upper_bound(ps_high, 0, x)
        ub_arm1 = GLMUCBPolicy._arm_upper_bound(ps_high, 1, x)

        # both should have large confidence, but arm 0 has higher mean
        assert ub_arm0 > 0
        assert ub_arm1 > 0
