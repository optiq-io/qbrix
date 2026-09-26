"""Unit tests for LogisticTSPolicy."""

import numpy as np
import pytest

from qbrixcore.policy.ts import LogisticTSPolicy
from qbrixcore.policy.ts import LogisticTSParamState
from qbrixcore.context import Context


class TestLogisticTSParamState:
    def test_param_state_creation_minimal(self):
        """test param state creation with minimal args."""
        ps = LogisticTSParamState(num_arms=3, dim=5)

        assert ps.num_arms == 3
        assert ps.dim == 5
        assert ps.lambda_ == 1.0
        assert ps.lr == 0.1
        assert ps.w.shape == (3, 5)
        assert ps.h.shape == (3, 5)

    def test_param_state_default_weights_are_zero(self):
        """test default weights are zero for each arm."""
        ps = LogisticTSParamState(num_arms=3, dim=4)

        assert np.all(ps.w == 0.0)

    def test_param_state_default_hessian_is_lambda(self):
        """test default Hessian diagonal is initialized to lambda."""
        ps = LogisticTSParamState(num_arms=3, dim=4, lambda_=2.0)

        assert np.all(ps.h == 2.0)

    def test_param_state_creation_with_custom_params(self):
        """test param state creation with custom hyperparameters."""
        ps = LogisticTSParamState(num_arms=3, dim=5, lambda_=0.5, lr=0.05)

        assert ps.lambda_ == 0.5
        assert ps.lr == 0.05

    def test_param_state_creation_with_custom_arrays(self):
        """test param state creation with pre-initialized arrays."""
        w = np.ones((2, 3))
        h = np.full((2, 3), 2.0)

        ps = LogisticTSParamState(num_arms=2, dim=3, w=w, h=h)

        assert np.array_equal(ps.w, w)
        assert np.array_equal(ps.h, h)

    def test_param_state_validation_num_arms_positive(self):
        """test param state validation requires positive num_arms."""
        with pytest.raises(ValueError):
            LogisticTSParamState(num_arms=0, dim=5)

    def test_param_state_validation_dim_positive(self):
        """test param state validation requires positive dim."""
        with pytest.raises(ValueError):
            LogisticTSParamState(num_arms=3, dim=0)

    def test_param_state_validation_lambda_positive(self):
        """test param state validation requires positive lambda."""
        with pytest.raises(ValueError):
            LogisticTSParamState(num_arms=3, dim=5, lambda_=0.0)

        with pytest.raises(ValueError):
            LogisticTSParamState(num_arms=3, dim=5, lambda_=-1.0)

    def test_param_state_validation_lr_bounds(self):
        """test param state validation requires lr in (0, 1]."""
        with pytest.raises(ValueError):
            LogisticTSParamState(num_arms=3, dim=5, lr=0.0)

        with pytest.raises(ValueError):
            LogisticTSParamState(num_arms=3, dim=5, lr=1.5)

    def test_param_state_id_is_unique(self):
        """test param state ids are unique."""
        ps1 = LogisticTSParamState(num_arms=3, dim=5)
        ps2 = LogisticTSParamState(num_arms=3, dim=5)

        assert ps1.id != ps2.id


class TestLogisticTSPolicy:
    def test_policy_name(self):
        """test policy has correct name."""
        assert LogisticTSPolicy.name == "LogisticTSPolicy"

    def test_policy_category(self):
        """test policy has correct category."""
        assert LogisticTSPolicy.category == "contextual"

    def test_policy_reward_types(self):
        """test policy supports only binary rewards."""
        from qbrixcore.policy._reward_type import RewardType

        assert LogisticTSPolicy.reward_types == [RewardType.BINARY]

    def test_policy_param_state_cls(self):
        """test policy has correct param state class."""
        assert LogisticTSPolicy.param_state_cls == LogisticTSParamState

    def test_init_params(self):
        """test init_params creates correct param state."""
        params = LogisticTSPolicy.build_state(num_arms=3, dim=5)

        assert isinstance(params, LogisticTSParamState)
        assert params.num_arms == 3
        assert params.dim == 5

    def test_init_params_with_custom_hyperparams(self):
        """test init_params with custom hyperparameters."""
        params = LogisticTSPolicy.build_state(num_arms=3, dim=5, lambda_=0.5, lr=0.05)

        assert params.lambda_ == 0.5
        assert params.lr == 0.05

    def test_to_vector_from_list(self):
        """test converting context vector from list to 1d array."""
        ctx = Context(vector=[1.0, 2.0, 3.0])

        v = LogisticTSPolicy._to_vector(ctx)

        assert isinstance(v, np.ndarray)
        assert v.shape == (3,)
        assert np.array_equal(v, [1.0, 2.0, 3.0])

    def test_to_vector_from_1d_array(self):
        """test converting context vector from 1d array."""
        ctx = Context(vector=np.array([1.0, 2.0, 3.0]))

        v = LogisticTSPolicy._to_vector(ctx)

        assert v.shape == (3,)

    def test_to_vector_from_column_vector(self):
        """test converting context vector from column vector to 1d."""
        ctx = Context(vector=np.array([[1.0], [2.0], [3.0]]))

        v = LogisticTSPolicy._to_vector(ctx)

        assert v.shape == (3,)

    def test_select_returns_valid_arm_index(self):
        """test select returns valid arm index."""
        ps = LogisticTSParamState(num_arms=3, dim=4)
        ctx = Context(vector=[1.0, 0.5, -0.3, 0.8])

        arm_index = LogisticTSPolicy.select(ps, ctx)

        assert isinstance(arm_index, int)
        assert 0 <= arm_index < 3

    def test_select_with_initial_state_explores(self):
        """test select with initial state explores all arms."""
        ps = LogisticTSParamState(num_arms=3, dim=4)
        ctx = Context(vector=[1.0, 0.5, -0.3, 0.8])

        selections = [LogisticTSPolicy.select(ps, ctx) for _ in range(100)]

        assert len(set(selections)) == 3

    def test_select_deterministic_with_seed(self):
        """test select is deterministic with fixed seed."""
        ps = LogisticTSParamState(num_arms=3, dim=4)
        ctx = Context(vector=[1.0, 0.5, -0.3, 0.8])

        np.random.seed(42)
        result1 = LogisticTSPolicy.select(ps, ctx)

        np.random.seed(42)
        result2 = LogisticTSPolicy.select(ps, ctx)

        assert result1 == result2

    def test_select_single_arm(self):
        """test select with single arm always returns 0."""
        ps = LogisticTSParamState(num_arms=1, dim=3)
        ctx = Context(vector=[1.0, 0.5, -0.3])

        arm_index = LogisticTSPolicy.select(ps, ctx)

        assert arm_index == 0

    def test_select_prefers_arm_with_higher_weights(self):
        """test select tends to prefer arm with higher learned weights."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        # give arm 0 strong positive weights
        ps.w[0] = np.array([5.0, 5.0])
        ps.w[1] = np.array([-5.0, -5.0])
        ps.w[2] = np.array([-5.0, -5.0])
        # tighten posterior so sampling doesn't override
        ps.h = np.full((3, 2), 100.0)

        ctx = Context(vector=[1.0, 1.0])

        selections = [LogisticTSPolicy.select(ps, ctx) for _ in range(100)]
        arm_0_count = selections.count(0)

        assert arm_0_count > 80

    def test_train_updates_weights(self):
        """test train updates weight vector for chosen arm."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        updated = LogisticTSPolicy.train(ps, ctx, choice=1, reward=1)

        assert not np.array_equal(updated.w[1], ps.w[1])
        # other arms unchanged
        assert np.array_equal(updated.w[0], ps.w[0])
        assert np.array_equal(updated.w[2], ps.w[2])

    def test_train_updates_hessian(self):
        """test train updates Hessian diagonal for chosen arm."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        updated = LogisticTSPolicy.train(ps, ctx, choice=1, reward=1)

        assert not np.array_equal(updated.h[1], ps.h[1])
        # other arms unchanged
        assert np.array_equal(updated.h[0], ps.h[0])
        assert np.array_equal(updated.h[2], ps.h[2])

    def test_train_does_not_mutate_original_params(self):
        """test train returns new params without mutating original."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])
        original_w = ps.w.copy()
        original_h = ps.h.copy()

        updated = LogisticTSPolicy.train(ps, ctx, choice=1, reward=1)

        assert np.array_equal(ps.w, original_w)
        assert np.array_equal(ps.h, original_h)
        assert not np.array_equal(updated.w[1], ps.w[1])

    def test_train_positive_reward_moves_weights_up(self):
        """test training with reward=1 increases predicted probability."""
        ps = LogisticTSParamState(num_arms=3, dim=2, lr=0.5)
        ctx = Context(vector=[1.0, 1.0])
        x = np.array([1.0, 1.0])

        # initial prediction at sigmoid(0) = 0.5
        logit_before = np.dot(ps.w[0], x)

        updated = LogisticTSPolicy.train(ps, ctx, choice=0, reward=1)

        logit_after = np.dot(updated.w[0], x)

        # reward=1 should push weights to increase logit
        assert logit_after > logit_before

    def test_train_negative_reward_moves_weights_down(self):
        """test training with reward=0 decreases predicted probability."""
        ps = LogisticTSParamState(num_arms=3, dim=2, lr=0.5)
        # start with positive weights so prediction > 0.5
        ps.w[0] = np.array([1.0, 1.0])
        ctx = Context(vector=[1.0, 1.0])
        x = np.array([1.0, 1.0])

        logit_before = np.dot(ps.w[0], x)

        updated = LogisticTSPolicy.train(ps, ctx, choice=0, reward=0)

        logit_after = np.dot(updated.w[0], x)

        assert logit_after < logit_before

    def test_train_multiple_updates_accumulate(self):
        """test train accumulates updates for same arm."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 1.0])

        for _ in range(10):
            ps = LogisticTSPolicy.train(ps, ctx, choice=0, reward=1)

        # weights should have moved from zero
        assert not np.allclose(ps.w[0], 0.0)
        # Hessian should have grown
        assert np.all(ps.h[0] > 1.0)

    def test_train_with_list_context_vector(self):
        """test train works with list context vector."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        updated = LogisticTSPolicy.train(ps, ctx, choice=0, reward=1)

        assert updated is not None
        assert not np.array_equal(updated.w[0], ps.w[0])

    def test_train_with_numpy_context_vector(self):
        """test train works with numpy array context vector."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=np.array([1.0, 2.0]))

        updated = LogisticTSPolicy.train(ps, ctx, choice=0, reward=1)

        assert updated is not None
        assert not np.array_equal(updated.w[0], ps.w[0])

    def test_train_with_numpy_reward(self):
        """test train handles numpy scalar reward."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        updated = LogisticTSPolicy.train(ps, ctx, choice=0, reward=np.float64(1.0))

        assert not np.array_equal(updated.w[0], ps.w[0])

    def test_integration_select_and_train(self):
        """test integration of select and train workflow."""
        ps = LogisticTSParamState(num_arms=3, dim=4)
        ctx = Context(vector=[1.0, 0.5, -0.3, 0.8])

        arm = LogisticTSPolicy.select(ps, ctx)
        assert 0 <= arm < 3

        updated_ps = LogisticTSPolicy.train(ps, ctx, choice=arm, reward=1)

        arm2 = LogisticTSPolicy.select(updated_ps, ctx)
        assert 0 <= arm2 < 3

    def test_integration_learns_best_arm(self):
        """test policy learns to prefer the best arm over many rounds."""
        ps = LogisticTSParamState(num_arms=3, dim=2, lr=0.3)
        ctx = Context(vector=[1.0, 1.0])

        # arm 0: 80% reward, arm 1: 20% reward, arm 2: 20% reward
        np.random.seed(42)
        for _ in range(200):
            arm = LogisticTSPolicy.select(ps, ctx)
            if arm == 0:
                reward = 1 if np.random.random() < 0.8 else 0
            else:
                reward = 1 if np.random.random() < 0.2 else 0
            ps = LogisticTSPolicy.train(ps, ctx, choice=arm, reward=reward)

        # after learning, arm 0 should be selected most
        selections = [LogisticTSPolicy.select(ps, ctx) for _ in range(100)]
        arm_0_count = selections.count(0)

        assert arm_0_count > 50

    def test_hessian_grows_monotonically(self):
        """test Hessian diagonal only increases (accumulates information)."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 2.0])

        for _ in range(10):
            h_before = ps.h[0].copy()
            ps = LogisticTSPolicy.train(ps, ctx, choice=0, reward=1)
            assert np.all(ps.h[0] >= h_before)

    def test_posterior_narrows_with_more_data(self):
        """test posterior variance decreases as more data is observed."""
        ps = LogisticTSParamState(num_arms=3, dim=2)
        ctx = Context(vector=[1.0, 1.0])

        # initial posterior std
        initial_std = 1.0 / np.sqrt(ps.h[0])

        for _ in range(50):
            ps = LogisticTSPolicy.train(ps, ctx, choice=0, reward=1)

        final_std = 1.0 / np.sqrt(ps.h[0])

        # posterior should be tighter
        assert np.all(final_std < initial_std)
