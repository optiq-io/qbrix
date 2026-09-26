"""unit tests for context vector validation on the select hot path.

invariants verified:
  - a contextual experiment rejects any width other than its dim
  - an absent vector counts as width 0, so it is rejected too
  - the message names both the received and the expected width
  - a non-contextual experiment ignores the vector entirely
  - a property name the schema never declared is rejected, not encoded away
  - dim is read from the same policy_params the redis record carries, for
    single-policy, learner and meta experiments alike
"""

from __future__ import annotations

import pytest

from proxysvc.core.error import ContextPropertiesError
from proxysvc.core.error import ContextVectorError
from proxysvc.mod.agent.service import _resolve_context_vector
from proxysvc.mod.agent.service import _validate_context_vector
from proxysvc.mod.experiment.cache import ExperimentState


def _state(**policy_params) -> ExperimentState:
    return ExperimentState(enabled=True, pool={}, policy_params=policy_params)


class TestContextualWidth:
    def test_correct_width_passes(self):
        _validate_context_vector(_state(dim=4), [0.1, 0.2, 0.3, 0.4])

    @pytest.mark.parametrize(
        "vector,width",
        [
            ([0.1, 0.2, 0.3], 3),
            ([0.1, 0.2, 0.3, 0.4, 0.5], 5),
            ([], 0),
            (None, 0),
        ],
    )
    def test_wrong_width_rejected(self, vector, width):
        with pytest.raises(ContextVectorError) as exc:
            _validate_context_vector(_state(dim=4), vector)
        assert f"width {width}" in str(exc.value)
        assert "expects 4" in str(exc.value)

    def test_message_names_both_widths(self):
        with pytest.raises(ContextVectorError) as exc:
            _validate_context_vector(_state(dim=4), [1.0, 2.0, 3.0])
        assert str(exc.value) == "context.vector has width 3, experiment expects 4"

    def test_dim_of_one_is_enforced(self):
        _validate_context_vector(_state(dim=1), [0.5])
        with pytest.raises(ContextVectorError):
            _validate_context_vector(_state(dim=1), [])


class TestNonContextual:
    def test_absent_vector_passes(self):
        _validate_context_vector(_state(), None)

    def test_supplied_vector_is_ignored(self):
        """stochastic policies ignore the vector; sending one stays valid."""
        _validate_context_vector(_state(epsilon=0.1), [0.1, 0.2, 0.3])

    @pytest.mark.parametrize("dim", [None, 0, -1, "4"])
    def test_unusable_dim_is_not_enforced(self, dim):
        """a missing or malformed dim must not turn every request into a 400."""
        _validate_context_vector(_state(dim=dim), None)


class TestMetaBandit:
    def test_contextual_meta_validates_against_its_own_dim(self):
        """a contextual meta experiment carries use_context + dim on the parent."""
        state = _state(use_context=True, dim=3, learners=["l-1", "l-2"])
        _validate_context_vector(state, [0.1, 0.2, 0.3])
        with pytest.raises(ContextVectorError):
            _validate_context_vector(state, [0.1, 0.2])

    def test_non_contextual_meta_ignores_the_vector(self):
        state = _state(reward_type="binary", learners=["l-1", "l-2"])
        _validate_context_vector(state, None)


class TestStateProjection:
    def test_policy_params_survives_the_slim_projection(self):
        """ExperimentState ignores extra keys; policy_params must not be one."""
        record = {
            "id": "exp-1",
            "tenant_id": "t-1",
            "name": "exp",
            "pool_id": "p-1",
            "pool": {"arms": []},
            "policy": "LinUCBPolicy",
            "policy_params": {"alpha": 1.0, "dim": 4},
            "enabled": True,
        }
        state = ExperimentState.model_validate(record)
        assert state.context_dim == 4


SCHEMA = [
    {"name": "device", "type": "categorical", "values": ["mobile", "desktop"]},
    {"name": "price", "type": "numeric", "min": 0.0, "max": 200.0},
]
# intercept + device(2 + other) + price = 5
SCHEMA_DIM = 5


def _schema_state() -> ExperimentState:
    return _state(context_schema=SCHEMA, dim=SCHEMA_DIM)


class TestResolveWithSchema:
    """a schema-backed experiment encodes named properties at the edge."""

    def test_properties_are_encoded(self):
        vector = _resolve_context_vector(
            _schema_state(), None, {"device": "desktop", "price": 100}
        )

        assert vector == [1.0, 0.0, 1.0, 0.0, 0.5]

    def test_absent_properties_serve_the_default_vector(self):
        """an absent context degrades to a real point, not a hole in feature space."""
        vector = _resolve_context_vector(_schema_state(), None, None)

        assert vector == [1.0, 0.0, 0.0, 1.0, 0.5]
        assert len(vector) == SCHEMA_DIM

    def test_partial_properties_fill_the_rest_with_defaults(self):
        vector = _resolve_context_vector(_schema_state(), None, {"device": "mobile"})

        assert vector == [1.0, 1.0, 0.0, 0.0, 0.5]

    def test_unseen_categorical_value_is_scored_not_rejected(self):
        vector = _resolve_context_vector(_schema_state(), None, {"device": "smart_tv"})

        assert vector == [1.0, 0.0, 0.0, 1.0, 0.5]

    def test_undeclared_property_is_rejected_at_the_edge(self):
        """the encoder's rejection reaches the caller as a 400, not a 500."""
        with pytest.raises(ContextPropertiesError) as exc:
            _resolve_context_vector(
                _schema_state(), None, {"device": "mobile", "session": "abc"}
            )

        assert "session" in str(exc.value)

    def test_encoded_width_always_matches_the_stored_dim(self):
        """the stored dim is what _validate_context_vector would have enforced."""
        state = _schema_state()

        for properties in (None, {}, {"device": "mobile"}, {"price": 9000}):
            assert len(_resolve_context_vector(state, None, properties)) == (
                state.context_dim
            )

    def test_bad_property_type_is_rejected_naming_the_property(self):
        with pytest.raises(ContextPropertiesError) as exc:
            _resolve_context_vector(_schema_state(), None, {"price": "expensive"})

        assert "price" in str(exc.value)

    def test_vector_against_a_schema_experiment_is_rejected(self):
        with pytest.raises(ContextPropertiesError) as exc:
            _resolve_context_vector(_schema_state(), [0.0] * SCHEMA_DIM, None)

        assert "send context.properties" in str(exc.value)


class TestResolveWithoutSchema:
    """the dim-only escape hatch validates width and rejects an absent vector."""

    def test_correct_width_vector_passes_through(self):
        assert _resolve_context_vector(_state(dim=4), [0.1] * 4, None) == [0.1] * 4

    def test_wrong_width_still_rejected(self):
        with pytest.raises(ContextVectorError):
            _resolve_context_vector(_state(dim=4), [0.1] * 3, None)

    def test_absent_vector_still_rejected(self):
        """without a schema there is no principled default to fall back to."""
        with pytest.raises(ContextVectorError):
            _resolve_context_vector(_state(dim=4), None, None)

    def test_properties_against_a_vector_experiment_are_rejected(self):
        with pytest.raises(ContextPropertiesError) as exc:
            _resolve_context_vector(_state(dim=4), None, {"device": "mobile"})

        assert "not created with a context schema" in str(exc.value)

    def test_non_contextual_ignores_properties(self):
        assert _resolve_context_vector(_state(), None, {"device": "mobile"}) is None

    def test_missing_state_passes_the_vector_through(self):
        assert _resolve_context_vector(None, [0.1, 0.2], None) == [0.1, 0.2]


class TestResolveMutualExclusion:
    def test_both_supplied_is_rejected(self):
        with pytest.raises(ContextPropertiesError) as exc:
            _resolve_context_vector(_schema_state(), [0.0] * SCHEMA_DIM, {"a": 1})

        assert "not both" in str(exc.value)

    def test_both_rejected_before_the_experiment_is_consulted(self):
        with pytest.raises(ContextPropertiesError):
            _resolve_context_vector(None, [0.0], {"a": 1})


class TestSchemaProjection:
    def test_schema_is_parsed_off_the_cached_record(self):
        state = _schema_state()

        assert state.context_schema is not None
        assert state.context_schema.dim == SCHEMA_DIM

    def test_schema_is_none_for_a_dim_only_experiment(self):
        assert _state(dim=4).context_schema is None

    def test_schema_is_parsed_once_per_state(self):
        """cached: the select path reads it per request while l1 holds it."""
        state = _schema_state()

        assert state.context_schema is state.context_schema
