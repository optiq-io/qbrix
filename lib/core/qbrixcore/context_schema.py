from __future__ import annotations

from typing import Annotated
from typing import Any
from typing import Literal
from typing import Union

from pydantic import BaseModel
from pydantic import Field
from pydantic import RootModel
from pydantic import model_validator

MAX_CONTEXT_DIM = 64

# every encoding opens with a constant slot. contextual policies fit
# theta_a.T x with no bias term, so without it an all-zero encoding predicts
# exactly 0 for every arm and an arm's baseline is unlearnable there.
_INTERCEPT = (1.0,)


class ContextEncodeError(ValueError):
    """raised when a supplied property value cannot be encoded by the schema."""


class _Property(BaseModel):
    """one declared property of a context.

    subclasses own their own width, their encoding, and the segment they
    contribute when the caller supplies nothing for them.
    """

    name: str = Field(..., min_length=1)

    @property
    def width(self) -> int:
        raise NotImplementedError

    def default(self) -> list[float]:
        raise NotImplementedError

    def encode(self, value: Any) -> list[float]:
        raise NotImplementedError


class CategoricalProperty(_Property):
    """a fixed set of values, one-hot encoded, plus a trailing `other` slot.

    the `other` slot is what makes the width stable: a value the schema has
    never seen is scored as `other` rather than rejected or given a new slot.
    """

    type: Literal["categorical"] = "categorical"
    values: list[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_values(self):
        if len(set(self.values)) != len(self.values):
            raise ValueError(f"property '{self.name}' declares duplicate values")
        return self

    @property
    def width(self) -> int:
        return len(self.values) + 1

    def default(self) -> list[float]:
        vector = [0.0] * self.width
        vector[-1] = 1.0
        return vector

    def encode(self, value: Any) -> list[float]:
        # bool before int: bool is a subclass of int, and a float is rejected
        # because "20.0" and "20" are not obviously the same category
        if isinstance(value, bool):
            token = "true" if value else "false"
        elif isinstance(value, str):
            token = value
        elif isinstance(value, int):
            token = str(value)
        else:
            raise ContextEncodeError(
                f"property '{self.name}' is categorical and accepts a string, "
                f"integer or boolean, got {type(value).__name__}"
            )

        vector = [0.0] * self.width
        try:
            vector[self.values.index(token)] = 1.0
        except ValueError:
            vector[-1] = 1.0
        return vector


class NumericProperty(_Property):
    """a scalar min-max normalized into [0, 1] and clamped to its declared range."""

    type: Literal["numeric"] = "numeric"
    min: float
    max: float

    @model_validator(mode="after")
    def _check_range(self):
        if self.min >= self.max:
            raise ValueError(
                f"property '{self.name}' needs min < max, "
                f"got min={self.min} max={self.max}"
            )
        return self

    @property
    def width(self) -> int:
        return 1

    def default(self) -> list[float]:
        return [0.5]

    def encode(self, value: Any) -> list[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContextEncodeError(
                f"property '{self.name}' is numeric and accepts a number, "
                f"got {type(value).__name__}"
            )
        clamped = min(max(float(value), self.min), self.max)
        return [(clamped - self.min) / (self.max - self.min)]


class BooleanProperty(_Property):
    """a single slot carrying 1.0 or 0.0."""

    type: Literal["boolean"] = "boolean"

    @property
    def width(self) -> int:
        return 1

    def default(self) -> list[float]:
        return [0.0]

    def encode(self, value: Any) -> list[float]:
        if not isinstance(value, bool):
            raise ContextEncodeError(
                f"property '{self.name}' is boolean and accepts true or false, "
                f"got {type(value).__name__}"
            )
        return [1.0 if value else 0.0]


ContextProperty = Annotated[
    Union[CategoricalProperty, NumericProperty, BooleanProperty],
    Field(discriminator="type"),
]


class ContextSchema(RootModel[list[ContextProperty]]):
    """the ordered set of properties an experiment accepts, and their encoding.

    serializes as a bare list, so it round-trips through the experiment's
    policy_params as `context_schema: [...]`. `dim` is derived from the
    properties plus the reserved intercept slot, and is never stored or
    supplied.
    """

    @model_validator(mode="after")
    def _check_schema(self):
        if not self.root:
            raise ValueError("context schema needs at least one property")

        names = [prop.name for prop in self.root]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"context schema declares duplicate property names: "
                f"{', '.join(duplicates)}"
            )

        if self.dim > MAX_CONTEXT_DIM:
            raise ValueError(
                f"context schema derives a width of {self.dim}, including "
                f"{len(_INTERCEPT)} reserved baseline slot, above the limit of "
                f"{MAX_CONTEXT_DIM}. every selection inverts a width x width matrix "
                f"per arm, so bucket high-cardinality properties (continent rather "
                f"than country) to bring it down"
            )
        return self

    @property
    def dim(self) -> int:
        return len(_INTERCEPT) + sum(prop.width for prop in self.root)

    def encode(self, properties: dict | None = None) -> list[float]:
        """encode supplied properties into a vector of exactly `dim` floats.

        opens with the reserved intercept slot. a property the caller omits
        contributes its default segment; a name the schema does not declare is
        rejected. one transposed letter would otherwise encode to defaults on
        every request, so the model trains against a constant vector for as
        long as nobody notices — and nothing anywhere would say so. the
        neighbouring failure, a value of the wrong type, is already loud.
        """
        supplied = properties or {}
        declared = {prop.name for prop in self.root}
        undeclared = sorted(set(supplied) - declared)
        if undeclared:
            raise ContextEncodeError(
                f"context properties not declared by this schema: "
                f"{', '.join(undeclared)}. declared: "
                f"{', '.join(prop.name for prop in self.root)}"
            )

        vector: list[float] = list(_INTERCEPT)
        for prop in self.root:
            value = supplied.get(prop.name)
            vector.extend(prop.default() if value is None else prop.encode(value))
        return vector

    def default_vector(self) -> list[float]:
        """the vector for a request that carries no properties at all."""
        return self.encode()
