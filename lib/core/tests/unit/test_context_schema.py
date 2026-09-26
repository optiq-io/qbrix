"""Unit tests for ContextSchema and its property encoders."""

import numpy as np
import pytest
from pydantic import ValidationError

from qbrixcore.context import Context
from qbrixcore.context_schema import MAX_CONTEXT_DIM
from qbrixcore.context_schema import BooleanProperty
from qbrixcore.context_schema import CategoricalProperty
from qbrixcore.context_schema import ContextEncodeError
from qbrixcore.context_schema import ContextSchema
from qbrixcore.context_schema import NumericProperty
from qbrixcore.policy.ucb import LinUCBPolicy


def build_schema():
    """intercept + device(2 values + other) + price + returning = width 6."""
    return ContextSchema.model_validate(
        [
            {"name": "device", "type": "categorical", "values": ["mobile", "desktop"]},
            {"name": "price", "type": "numeric", "min": 0, "max": 200},
            {"name": "returning", "type": "boolean"},
        ]
    )


class TestDim:
    def test_dim_is_derived_from_properties(self):
        """intercept + categorical len(values)+1 + numeric 1 + boolean 1."""
        schema = build_schema()

        assert schema.dim == 6

    def test_dim_cannot_be_set(self):
        """dim is a read-only derived property, never stored."""
        schema = build_schema()

        with pytest.raises(AttributeError):
            schema.dim = 12

    def test_dim_ignores_an_undeclared_dim_key(self):
        """a caller cannot smuggle dim in through the serialized form."""
        schema = ContextSchema.model_validate(
            [{"name": "returning", "type": "boolean", "dim": 99}]
        )

        assert schema.dim == 2


class TestCategoricalEncoding:
    def test_known_value_sets_its_own_slot(self):
        prop = CategoricalProperty(name="device", values=["mobile", "desktop"])

        assert prop.encode("mobile") == [1.0, 0.0, 0.0]
        assert prop.encode("desktop") == [0.0, 1.0, 0.0]

    def test_unseen_value_lands_in_the_other_slot(self):
        """a value the schema has never seen is scored, not rejected."""
        prop = CategoricalProperty(name="device", values=["mobile", "desktop"])

        assert prop.encode("smart_tv") == [0.0, 0.0, 1.0]

    def test_default_is_the_other_slot(self):
        prop = CategoricalProperty(name="device", values=["mobile", "desktop"])

        assert prop.default() == [0.0, 0.0, 1.0]

    def test_integer_is_coerced_to_its_string_form(self):
        """json callers send numeric-looking category codes as numbers."""
        prop = CategoricalProperty(name="tier", values=["1", "2", "3"])

        assert prop.encode(3) == [0.0, 0.0, 1.0, 0.0]

    def test_boolean_is_coerced_to_true_false(self):
        prop = CategoricalProperty(name="state", values=["true", "false"])

        assert prop.encode(True) == [1.0, 0.0, 0.0]
        assert prop.encode(False) == [0.0, 1.0, 0.0]

    def test_float_is_rejected(self):
        """3.0 and "3" are not obviously the same category."""
        prop = CategoricalProperty(name="tier", values=["1", "2", "3"])

        with pytest.raises(ContextEncodeError, match="tier"):
            prop.encode(3.0)

    def test_list_is_rejected(self):
        prop = CategoricalProperty(name="device", values=["mobile"])

        with pytest.raises(ContextEncodeError, match="categorical"):
            prop.encode(["mobile"])


class TestNumericEncoding:
    def test_value_is_min_max_normalized(self):
        prop = NumericProperty(name="price", min=0, max=200)

        assert prop.encode(0) == [0.0]
        assert prop.encode(100) == [0.5]
        assert prop.encode(200) == [1.0]

    def test_non_zero_minimum_is_handled(self):
        prop = NumericProperty(name="age", min=20, max=40)

        assert prop.encode(30) == [0.5]

    def test_value_outside_the_range_is_clamped(self):
        prop = NumericProperty(name="price", min=0, max=200)

        assert prop.encode(-50) == [0.0]
        assert prop.encode(9000) == [1.0]

    def test_default_is_the_midpoint(self):
        """absent data means an average request, not a request at the minimum."""
        prop = NumericProperty(name="price", min=0, max=200)

        assert prop.default() == [0.5]

    def test_string_is_rejected(self):
        prop = NumericProperty(name="price", min=0, max=200)

        with pytest.raises(ContextEncodeError, match="numeric"):
            prop.encode("20")

    def test_boolean_is_rejected(self):
        """bool is a subclass of int and must not slip through as 0/1."""
        prop = NumericProperty(name="price", min=0, max=200)

        with pytest.raises(ContextEncodeError, match="price"):
            prop.encode(True)


class TestBooleanEncoding:
    def test_true_and_false(self):
        prop = BooleanProperty(name="returning")

        assert prop.encode(True) == [1.0]
        assert prop.encode(False) == [0.0]

    def test_default_is_false(self):
        prop = BooleanProperty(name="returning")

        assert prop.default() == [0.0]

    def test_non_boolean_is_rejected(self):
        prop = BooleanProperty(name="returning")

        with pytest.raises(ContextEncodeError, match="boolean"):
            prop.encode(1)


class TestSchemaEncode:
    def test_full_properties_encode_in_declared_order(self):
        schema = build_schema()

        vector = schema.encode({"device": "desktop", "price": 50, "returning": True})

        assert vector == [1.0, 0.0, 1.0, 0.0, 0.25, 1.0]

    def test_absent_property_uses_its_default_segment(self):
        """an omitted property contributes exactly what default_vector would."""
        schema = build_schema()

        vector = schema.encode({"device": "mobile"})

        assert vector == [1.0, 1.0, 0.0, 0.0, 0.5, 0.0]

    def test_undeclared_property_is_rejected(self):
        """a typo would otherwise encode to defaults on every request, silently."""
        schema = build_schema()

        with pytest.raises(ContextEncodeError) as exc:
            schema.encode({"device": "mobile", "session_id": "abc-123"})

        assert "session_id" in str(exc.value)
        assert "declared: device" in str(exc.value)

    def test_the_message_names_every_undeclared_property(self):
        schema = build_schema()

        with pytest.raises(ContextEncodeError) as exc:
            schema.encode({"devise": "mobile", "prise": 10})

        assert "devise" in str(exc.value)
        assert "prise" in str(exc.value)

    def test_omitting_a_declared_property_is_still_fine(self):
        """absent is not the same as undeclared — it takes its default segment."""
        schema = build_schema()

        assert schema.encode({"device": "mobile"}) == schema.encode(
            {"device": "mobile"}
        )
        assert len(schema.encode({})) == schema.dim

    def test_none_encodes_as_the_default_vector(self):
        schema = build_schema()

        assert schema.encode(None) == schema.default_vector()

    def test_empty_dict_encodes_as_the_default_vector(self):
        schema = build_schema()

        assert schema.encode({}) == schema.default_vector()

    def test_default_vector_is_every_property_default(self):
        schema = build_schema()

        assert schema.default_vector() == [1.0, 0.0, 0.0, 1.0, 0.5, 0.0]

    def test_a_bad_value_names_the_offending_property(self):
        schema = build_schema()

        with pytest.raises(ContextEncodeError, match="price"):
            schema.encode({"price": "expensive"})


class TestIntercept:
    """the reserved constant slot.

    contextual policies fit theta_a.T x with no bias term, so an all-zero
    encoding predicts 0 for every arm no matter how much has been learned.
    the intercept keeps a per-arm baseline learnable everywhere in the space.
    """

    def test_numerics_only_schema_is_never_all_zero(self):
        """the case that motivated this: price at its minimum encodes to 0.0."""
        schema = ContextSchema.model_validate(
            [{"name": "price", "type": "numeric", "min": 0, "max": 200}]
        )

        assert schema.dim == 2
        assert schema.encode({"price": 0}) == [1.0, 0.0]

    def test_boolean_only_schema_is_never_all_zero(self):
        schema = ContextSchema.model_validate(
            [{"name": "returning", "type": "boolean"}]
        )

        assert schema.encode({"returning": False}) == [1.0, 0.0]

    def test_default_vector_carries_the_intercept(self):
        schema = ContextSchema.model_validate(
            [{"name": "price", "type": "numeric", "min": 0, "max": 200}]
        )

        assert schema.default_vector() == [1.0, 0.5]

    def test_the_intercept_slot_cannot_be_supplied(self):
        """it is reserved: not a name a caller can send, and never overridable."""
        schema = build_schema()

        with pytest.raises(ContextEncodeError):
            schema.encode({"intercept": 0.0})

        assert schema.encode({"device": "mobile"})[0] == 1.0

    def test_linucb_learns_a_per_arm_baseline_at_the_origin(self):
        """the behaviour the slot exists for, asserted against the real policy.

        without it both arms estimate exactly 0.0 here however much they have
        seen, and selection falls through to the exploration term alone.
        """
        schema = ContextSchema.model_validate(
            [{"name": "price", "type": "numeric", "min": 0, "max": 200}]
        )
        context = Context(vector=schema.encode({"price": 0}))

        state = LinUCBPolicy.build_state(num_arms=2, dim=schema.dim)
        for _ in range(50):
            state = LinUCBPolicy.train(ps=state, context=context, choice=0, reward=1.0)
            state = LinUCBPolicy.train(ps=state, context=context, choice=1, reward=0.0)

        x = np.asarray(context.vector, dtype=np.float64).reshape(-1, 1)
        estimates = [
            float(np.dot(np.dot(np.linalg.inv(state.d[arm]), state.r[arm]).T, x).item())
            for arm in (0, 1)
        ]

        assert estimates[0] > 0.9
        assert estimates[1] == pytest.approx(0.0)


class TestSchemaValidation:
    def test_empty_schema_is_rejected(self):
        with pytest.raises(ValidationError, match="at least one property"):
            ContextSchema.model_validate([])

    def test_duplicate_property_names_are_rejected(self):
        with pytest.raises(ValidationError, match="duplicate property names"):
            ContextSchema.model_validate(
                [
                    {"name": "device", "type": "categorical", "values": ["mobile"]},
                    {"name": "device", "type": "boolean"},
                ]
            )

    def test_categorical_with_no_values_is_rejected(self):
        with pytest.raises(ValidationError):
            ContextSchema.model_validate(
                [{"name": "device", "type": "categorical", "values": []}]
            )

    def test_categorical_with_duplicate_values_is_rejected(self):
        with pytest.raises(ValidationError, match="duplicate values"):
            ContextSchema.model_validate(
                [
                    {
                        "name": "device",
                        "type": "categorical",
                        "values": ["mobile", "mobile"],
                    }
                ]
            )

    def test_numeric_with_inverted_range_is_rejected(self):
        with pytest.raises(ValidationError, match="min < max"):
            ContextSchema.model_validate(
                [{"name": "price", "type": "numeric", "min": 200, "max": 0}]
            )

    def test_unknown_property_type_is_rejected(self):
        with pytest.raises(ValidationError):
            ContextSchema.model_validate([{"name": "domain", "type": "hashed"}])

    def test_over_wide_schema_is_rejected_naming_the_computed_width(self):
        countries = [f"c{i}" for i in range(MAX_CONTEXT_DIM)]  # + other + intercept

        with pytest.raises(ValidationError) as exc:
            ContextSchema.model_validate(
                [{"name": "country", "type": "categorical", "values": countries}]
            )

        assert str(MAX_CONTEXT_DIM + 2) in str(exc.value)
        assert str(MAX_CONTEXT_DIM) in str(exc.value)

    def test_schema_at_exactly_the_limit_is_accepted(self):
        values = [f"c{i}" for i in range(MAX_CONTEXT_DIM - 2)]
        schema = ContextSchema.model_validate(
            [{"name": "country", "type": "categorical", "values": values}]
        )

        assert schema.dim == MAX_CONTEXT_DIM


class TestSerialization:
    def test_schema_round_trips_as_a_bare_list(self):
        """the stored form in policy_params is a list, not a wrapper object."""
        declared = [
            {"name": "device", "type": "categorical", "values": ["mobile"]},
            {"name": "price", "type": "numeric", "min": 0.0, "max": 200.0},
            {"name": "returning", "type": "boolean"},
        ]
        dumped = ContextSchema.model_validate(declared).model_dump()

        assert isinstance(dumped, list)
        assert dumped == declared
        assert ContextSchema.model_validate(dumped).dim == 5


class TestEncodeWidthInvariant:
    @pytest.mark.parametrize(
        "declared",
        [
            [{"name": "a", "type": "boolean"}],
            [{"name": "a", "type": "numeric", "min": -10, "max": 10}],
            [{"name": "a", "type": "categorical", "values": ["x"]}],
            [
                {"name": "a", "type": "categorical", "values": ["x", "y", "z"]},
                {"name": "b", "type": "numeric", "min": 0, "max": 1},
                {"name": "c", "type": "boolean"},
                {"name": "d", "type": "categorical", "values": ["p", "q"]},
            ],
        ],
    )
    @pytest.mark.parametrize(
        "supplied",
        [
            None,
            {},
            {"a": "x"},
            {"a": True},
            {"a": 0},
            {"b": 999, "c": False, "unknown": "ignored"},
        ],
    )
    def test_output_length_always_equals_dim(self, declared, supplied):
        """whatever the caller sends, the vector the policies see is dim wide."""
        schema = ContextSchema.model_validate(declared)

        try:
            vector = schema.encode(supplied)
        except ContextEncodeError:
            return

        assert len(vector) == schema.dim
        assert vector[0] == 1.0
