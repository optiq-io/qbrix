"""unit tests for policy_params validation."""

from __future__ import annotations

import pytest

from proxysvc.util import _assert_context_dim_unchanged
from proxysvc.util import _assert_context_schema_unchanged
from proxysvc.util import _inspect_params
from proxysvc.util import _resolve_context_schema
from proxysvc.core.error import BadPolicyParamsError
from proxysvc.core.error import ContextDimImmutableError
from proxysvc.core.error import ContextSchemaImmutableError


class TestValidatePolicyParams:
    def test_beta_ts_with_empty_params_passes(self):
        _inspect_params("BetaTSPolicy", {})

    def test_beta_ts_with_none_params_passes(self):
        _inspect_params("BetaTSPolicy", None)

    def test_beta_ts_with_valid_params_passes(self):
        _inspect_params("BetaTSPolicy", {"alpha_prior": 2.0, "beta_prior": 2.0})

    def test_dirichlet_ts_with_required_param_passes(self):
        _inspect_params("DirichletTSPolicy", {"k": 3})

    def test_dirichlet_ts_with_full_params_passes(self):
        _inspect_params(
            "DirichletTSPolicy",
            {"k": 5, "concentration_prior": 0.5},
        )

    def test_dirichlet_ts_missing_required_param_raises(self):
        with pytest.raises(BadPolicyParamsError) as exc_info:
            _inspect_params("DirichletTSPolicy", {"concentration_prior": 1.0})
        assert "k" in str(exc_info.value)

    def test_dirichlet_ts_out_of_range_concentration_raises(self):
        with pytest.raises(BadPolicyParamsError) as exc_info:
            _inspect_params(
                "DirichletTSPolicy",
                {"k": 3, "concentration_prior": -1.0},
            )
        assert "concentration_prior" in str(exc_info.value)

    def test_dirichlet_ts_out_of_range_k_raises(self):
        # k must be > 1
        with pytest.raises(BadPolicyParamsError):
            _inspect_params("DirichletTSPolicy", {"k": 1})

    def test_unknown_policy_raises(self):
        with pytest.raises(BadPolicyParamsError) as exc_info:
            _inspect_params("NotARealPolicy", {})
        assert "unknown policy" in str(exc_info.value)

    def test_extra_unknown_param_is_accepted(self):
        # BaseParamState uses extra="allow"; unknown keys are silently ignored
        # rather than rejected. typos won't be caught here — known limitation.
        _inspect_params(
            "DirichletTSPolicy",
            {"k": 3, "totally_made_up_param": 42},
        )


class TestResolveContextSchema:
    """dim is derived from a declared schema, never supplied alongside it."""

    SCHEMA = [
        {"name": "device", "type": "categorical", "values": ["mobile", "desktop"]},
        {"name": "price", "type": "numeric", "min": 0, "max": 200},
    ]

    def test_params_without_a_schema_pass_through(self):
        """the dim-only escape hatch keeps working untouched."""
        params = _resolve_context_schema({"alpha": 1.5, "dim": 4})

        assert params == {"alpha": 1.5, "dim": 4}

    def test_none_becomes_an_empty_dict(self):
        assert _resolve_context_schema(None) == {}

    def test_dim_is_derived_and_materialized(self):
        """intercept + device(2+other) + price = 5."""
        params = _resolve_context_schema({"context_schema": self.SCHEMA})

        assert params["dim"] == 5

    def test_derived_params_satisfy_the_contextual_param_state(self):
        """the derived dim is what makes _inspect_params pass for LinUCB."""
        params = _resolve_context_schema({"context_schema": self.SCHEMA})

        _inspect_params("LinUCBPolicy", params)

    def test_schema_is_stored_canonically(self):
        """0 becomes 0.0, so a later comparison is not defeated by json typing."""
        params = _resolve_context_schema({"context_schema": self.SCHEMA})

        assert params["context_schema"][1]["min"] == 0.0
        assert isinstance(params["context_schema"][1]["min"], float)

    def test_input_is_not_mutated(self):
        original = {"context_schema": self.SCHEMA}
        _resolve_context_schema(original)

        assert "dim" not in original

    def test_schema_with_explicit_dim_is_rejected(self):
        with pytest.raises(BadPolicyParamsError) as exc:
            _resolve_context_schema({"context_schema": self.SCHEMA, "dim": 5})

        assert "dim is derived" in str(exc.value)

    def test_malformed_schema_is_rejected(self):
        with pytest.raises(BadPolicyParamsError) as exc:
            _resolve_context_schema(
                {"context_schema": [{"name": "device", "type": "categorical"}]}
            )

        assert "invalid context_schema" in str(exc.value)

    def test_over_wide_schema_is_rejected(self):
        countries = [f"c{i}" for i in range(80)]

        with pytest.raises(BadPolicyParamsError) as exc:
            _resolve_context_schema(
                {
                    "context_schema": [
                        {
                            "name": "country",
                            "type": "categorical",
                            "values": countries,
                        }
                    ]
                }
            )

        assert "82" in str(exc.value)


class TestAssertContextSchemaUnchanged:
    """context_schema is fixed at creation, like the pool's arms and the policy."""

    STORED = _resolve_context_schema(
        {
            "context_schema": [
                {"name": "device", "type": "categorical", "values": ["mobile"]},
            ]
        }
    )

    def test_identical_schema_passes(self):
        """tuning another param while resending the same schema is allowed."""
        incoming = _resolve_context_schema(
            {"context_schema": self.STORED["context_schema"], "alpha": 2.0}
        )

        _assert_context_schema_unchanged(self.STORED, incoming)

    def test_no_schema_on_either_side_passes(self):
        _assert_context_schema_unchanged({"dim": 4}, {"dim": 4})

    def test_altered_schema_is_rejected(self):
        incoming = _resolve_context_schema(
            {
                "context_schema": [
                    {
                        "name": "device",
                        "type": "categorical",
                        "values": ["mobile", "desktop"],
                    }
                ]
            }
        )

        with pytest.raises(ContextSchemaImmutableError) as exc:
            _assert_context_schema_unchanged(self.STORED, incoming)

        assert "differ from the stored" in str(exc.value)

    def test_omitting_the_schema_is_rejected_as_a_removal(self):
        """policy_params is replaced wholesale, so omission would drop it."""
        with pytest.raises(ContextSchemaImmutableError) as exc:
            _assert_context_schema_unchanged(self.STORED, {"alpha": 2.0})

        assert "would drop it" in str(exc.value)

    def test_adding_a_schema_to_a_vector_experiment_is_rejected(self):
        with pytest.raises(ContextSchemaImmutableError) as exc:
            _assert_context_schema_unchanged({"dim": 4}, self.STORED)

        assert "not created with a context schema" in str(exc.value)


class TestAssertContextDimUnchanged:
    """dim shapes the learned arrays, so it is fixed at creation like the schema."""

    def test_identical_dim_passes(self):
        _assert_context_dim_unchanged(
            {"dim": 4, "alpha": 1.5}, {"dim": 4, "alpha": 2.0}
        )

    def test_no_dim_on_either_side_passes(self):
        """a non-contextual experiment has no width to protect."""
        _assert_context_dim_unchanged({"alpha_prior": 1.0}, {"alpha_prior": 2.0})

    def test_widening_is_rejected_naming_both_widths(self):
        with pytest.raises(ContextDimImmutableError) as exc:
            _assert_context_dim_unchanged({"dim": 4}, {"dim": 6})

        assert "stored width is 4" in str(exc.value)
        assert "requested 6" in str(exc.value)

    def test_omitting_dim_is_rejected_as_a_removal(self):
        with pytest.raises(ContextDimImmutableError):
            _assert_context_dim_unchanged({"dim": 4}, {"alpha": 2.0})

    def test_adding_dim_to_a_non_contextual_experiment_is_rejected(self):
        with pytest.raises(ContextDimImmutableError):
            _assert_context_dim_unchanged({"alpha_prior": 1.0}, {"dim": 4})

    def test_an_unchanged_schema_derives_an_unchanged_dim(self):
        """the guard is a no-op for schema experiments, which is why it runs second."""
        stored = _resolve_context_schema(
            {
                "context_schema": [
                    {"name": "device", "type": "categorical", "values": ["mobile"]},
                ]
            }
        )
        incoming = _resolve_context_schema(
            {"context_schema": stored["context_schema"], "alpha": 2.0}
        )

        _assert_context_dim_unchanged(stored, incoming)
