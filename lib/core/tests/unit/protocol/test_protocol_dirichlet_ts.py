"""Unit tests for DirichletTSPolicy."""

import numpy as np
import pytest

from qbrixcore.policy.ts import DirichletTSPolicy
from qbrixcore.policy.ts import DirichletTSParamState
from qbrixcore.context import Context


class TestDirichletTSParamState:
    def test_param_state_creation_minimal(self):
        """test param state creation with required k."""
        ps = DirichletTSParamState(num_arms=3, k=4)

        assert ps.num_arms == 3
        assert ps.k == 4
        assert ps.concentration_prior == 1.0
        assert ps.alpha.shape == (3, 4)
        assert ps.T.shape == (3,)
        assert np.all(ps.alpha == 1.0)
        assert np.all(ps.T == 0)

    def test_param_state_creation_with_custom_concentration(self):
        """test param state creation with custom concentration prior."""
        ps = DirichletTSParamState(num_arms=2, k=3, concentration_prior=0.5)

        assert ps.concentration_prior == 0.5
        assert np.all(ps.alpha == 0.5)

    def test_param_state_creation_with_custom_arrays(self):
        """test param state creation with pre-initialized arrays."""
        alpha = np.array([[2.0, 3.0, 1.0], [1.0, 1.0, 5.0]], dtype=np.float64)
        T = np.array([5, 6], dtype=np.int64)

        ps = DirichletTSParamState(num_arms=2, k=3, alpha=alpha, T=T)

        assert np.array_equal(ps.alpha, alpha)
        assert np.array_equal(ps.T, T)

    def test_param_state_validation_num_arms_positive(self):
        """test param state validation requires positive num_arms."""
        with pytest.raises(ValueError):
            DirichletTSParamState(num_arms=0, k=3)

        with pytest.raises(ValueError):
            DirichletTSParamState(num_arms=-1, k=3)

    def test_param_state_validation_k_greater_than_one(self):
        """test param state validation requires k > 1."""
        with pytest.raises(ValueError):
            DirichletTSParamState(num_arms=3, k=1)

        with pytest.raises(ValueError):
            DirichletTSParamState(num_arms=3, k=0)

    def test_param_state_validation_concentration_prior_positive(self):
        """test param state validation requires positive concentration_prior."""
        with pytest.raises(ValueError):
            DirichletTSParamState(num_arms=3, k=3, concentration_prior=0.0)

        with pytest.raises(ValueError):
            DirichletTSParamState(num_arms=3, k=3, concentration_prior=-1.0)

    def test_param_state_id_is_unique(self):
        """test param state ids are unique."""
        ps1 = DirichletTSParamState(num_arms=3, k=4)
        ps2 = DirichletTSParamState(num_arms=3, k=4)

        assert ps1.id != ps2.id


class TestDirichletTSPolicy:
    def test_policy_name(self):
        """test policy has correct name."""
        assert DirichletTSPolicy.name == "DirichletTSPolicy"

    def test_policy_param_state_cls(self):
        """test policy has correct param state class."""
        assert DirichletTSPolicy.param_state_cls == DirichletTSParamState

    def test_policy_category(self):
        """test policy is categorized as stochastic."""
        assert DirichletTSPolicy.category == "stochastic"

    def test_init_params(self):
        """test init_params creates correct param state."""
        params = DirichletTSPolicy.build_state(num_arms=4, k=5)

        assert isinstance(params, DirichletTSParamState)
        assert params.num_arms == 4
        assert params.k == 5

    def test_init_params_with_custom_concentration(self):
        """test init_params with custom concentration prior."""
        params = DirichletTSPolicy.build_state(
            num_arms=3,
            k=4,
            concentration_prior=2.0,
        )

        assert params.concentration_prior == 2.0
        assert np.all(params.alpha == 2.0)

    def test_select_returns_valid_arm_index(self):
        """test select returns valid arm index."""
        ps = DirichletTSParamState(num_arms=5, k=3)
        ctx = Context()

        arm_index = DirichletTSPolicy.select(ps, ctx)

        assert isinstance(arm_index, int)
        assert 0 <= arm_index < 5

    def test_select_single_arm(self):
        """test select with single arm always returns 0."""
        ps = DirichletTSParamState(num_arms=1, k=3)
        ctx = Context()

        arm_index = DirichletTSPolicy.select(ps, ctx)

        assert arm_index == 0

    def test_select_favors_arm_with_high_outcome_mass(self):
        """test select prefers arm whose posterior concentrates on high-value outcomes."""
        # arm 0: posterior heavily on outcome 2 (highest value with K=3, values=[0,1,2])
        # arm 1: posterior heavily on outcome 0 (lowest value)
        alpha = np.array(
            [
                [1.0, 1.0, 200.0],  # arm 0: almost certain outcome 2
                [200.0, 1.0, 1.0],  # arm 1: almost certain outcome 0
            ],
            dtype=np.float64,
        )
        ps = DirichletTSParamState(num_arms=2, k=3, alpha=alpha)
        ctx = Context()

        selections = [DirichletTSPolicy.select(ps, ctx) for _ in range(100)]
        arm_0_count = selections.count(0)

        assert arm_0_count > 80

    def test_select_deterministic_with_seed(self):
        """test select is deterministic with fixed seed."""
        ps = DirichletTSParamState(num_arms=3, k=4)
        ctx = Context()

        np.random.seed(42)
        result1 = DirichletTSPolicy.select(ps, ctx)

        np.random.seed(42)
        result2 = DirichletTSPolicy.select(ps, ctx)

        assert result1 == result2

    def test_train_increments_correct_outcome_bucket(self):
        """test train increments alpha for the observed outcome and chosen arm."""
        ps = DirichletTSParamState(num_arms=3, k=4)
        ctx = Context()

        updated = DirichletTSPolicy.train(ps, ctx, choice=1, reward=2)

        # only arm 1, outcome 2 should change
        assert updated.alpha[1, 2] == 2.0
        assert updated.alpha[1, 0] == 1.0
        assert updated.alpha[1, 1] == 1.0
        assert updated.alpha[1, 3] == 1.0
        # other arms unchanged
        assert np.all(updated.alpha[0] == 1.0)
        assert np.all(updated.alpha[2] == 1.0)

    def test_train_increments_pull_count(self):
        """test train increments T for chosen arm."""
        ps = DirichletTSParamState(num_arms=3, k=4)
        ctx = Context()

        updated = DirichletTSPolicy.train(ps, ctx, choice=2, reward=1)

        assert updated.T[2] == 1
        assert updated.T[0] == 0
        assert updated.T[1] == 0

    def test_train_multiple_updates_accumulate(self):
        """test train accumulates multiple updates correctly."""
        ps = DirichletTSParamState(num_arms=2, k=3)
        ctx = Context()

        ps = DirichletTSPolicy.train(ps, ctx, choice=0, reward=0)
        ps = DirichletTSPolicy.train(ps, ctx, choice=0, reward=0)
        ps = DirichletTSPolicy.train(ps, ctx, choice=0, reward=2)

        assert ps.alpha[0, 0] == 3.0  # two outcome-0 observations + prior 1
        assert ps.alpha[0, 1] == 1.0  # unchanged
        assert ps.alpha[0, 2] == 2.0  # one outcome-2 observation + prior 1
        assert ps.T[0] == 3

    def test_train_does_not_mutate_original_params(self):
        """test train returns new params without mutating original."""
        ps = DirichletTSParamState(num_arms=3, k=4)
        ctx = Context()
        original_alpha = ps.alpha.copy()
        original_T = ps.T.copy()

        updated = DirichletTSPolicy.train(ps, ctx, choice=1, reward=2)

        assert np.array_equal(ps.alpha, original_alpha)
        assert np.array_equal(ps.T, original_T)
        assert updated.alpha[1, 2] == 2.0

    def test_train_clamps_out_of_range_reward(self):
        """test train clips rewards outside [0, k-1] to valid range."""
        ps = DirichletTSParamState(num_arms=2, k=4)
        ctx = Context()

        # reward > max valid outcome (3) should be clipped to 3
        updated = DirichletTSPolicy.train(ps, ctx, choice=0, reward=99)
        assert updated.alpha[0, 3] == 2.0

        # reward < 0 should be clipped to 0
        updated = DirichletTSPolicy.train(ps, ctx, choice=0, reward=-5)
        assert updated.alpha[0, 0] == 2.0

    def test_train_rounds_float_reward_to_nearest_outcome(self):
        """test train rounds continuous reward to the nearest integer outcome."""
        ps = DirichletTSParamState(num_arms=2, k=5)
        ctx = Context()

        # 1.6 rounds to 2
        updated = DirichletTSPolicy.train(ps, ctx, choice=0, reward=1.6)
        assert updated.alpha[0, 2] == 2.0

        # 0.4 rounds to 0
        updated = DirichletTSPolicy.train(ps, ctx, choice=0, reward=0.4)
        assert updated.alpha[0, 0] == 2.0

    def test_train_with_numpy_reward(self):
        """test train handles numpy scalar reward."""
        ps = DirichletTSParamState(num_arms=3, k=4)
        ctx = Context()

        updated = DirichletTSPolicy.train(ps, ctx, choice=0, reward=np.float64(1.0))

        assert updated.alpha[0, 1] == 2.0

    def test_outcome_values_default_unit_spacing(self):
        """test _outcome_values returns 0..K-1 with unit spacing."""
        values = DirichletTSPolicy._outcome_values(5)

        assert np.array_equal(values, np.array([0.0, 1.0, 2.0, 3.0, 4.0]))

    def test_select_two_outcome_equivalent_to_beta_structure(self):
        """test that with K=2 outcomes, Dirichlet reduces to Beta behavior structure.

        with k=2, alpha[:,0] tracks failures and alpha[:,1] tracks
        successes. arm with more successes should be preferred.
        """
        alpha = np.array(
            [
                [1.0, 100.0],  # arm 0: ~100 successes
                [100.0, 1.0],  # arm 1: ~100 failures
            ],
            dtype=np.float64,
        )
        ps = DirichletTSParamState(num_arms=2, k=2, alpha=alpha)
        ctx = Context()

        selections = [DirichletTSPolicy.select(ps, ctx) for _ in range(100)]
        arm_0_count = selections.count(0)

        assert arm_0_count > 80

    def test_user_params_excludes_array_fields(self):
        """test user_params exposes scalar user-configurable fields only."""
        params = DirichletTSPolicy.user_params()
        param_names = {p.name for p in params}

        # should expose scalar user params
        assert "k" in param_names
        assert "concentration_prior" in param_names
        # should not expose array state or internal fields
        assert "alpha" not in param_names
        assert "T" not in param_names
        assert "num_arms" not in param_names

    def test_user_params_k_required(self):
        """test k is marked as required in user params."""
        params = DirichletTSPolicy.user_params()
        k_param = next(p for p in params if p.name == "k")

        assert k_param.required is True

    def test_user_params_concentration_prior_has_default(self):
        """test concentration_prior is optional with default 1.0."""
        params = DirichletTSPolicy.user_params()
        conc_param = next(p for p in params if p.name == "concentration_prior")

        assert conc_param.required is False
        assert conc_param.default == 1.0

    def test_policy_in_registry(self):
        """test DirichletTSPolicy is registered in the POLICIES list."""
        from qbrixcore.policy import POLICIES

        policy_names = [p.name for p in POLICIES]
        assert "DirichletTSPolicy" in policy_names

    def test_policy_exported_from_init(self):
        """test DirichletTSPolicy is exported from qbrixcore.policy."""
        from qbrixcore.policy import DirichletTSPolicy as imported

        assert imported is DirichletTSPolicy
