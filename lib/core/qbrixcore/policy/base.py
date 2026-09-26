from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, get_args

from pydantic_core import PydanticUndefined

from qbrixcore.param.spec import PolicyParam
from qbrixcore.param.state import BaseParamState
from qbrixcore.param.var import _UserConfigurable
from qbrixcore.policy._reward_type import RewardType


class BasePolicy(ABC):
    """base class for all bandit policies."""

    param_state_cls: type[BaseParamState]

    # subclasses must define these
    reward_types: ClassVar[list[RewardType]]
    category: ClassVar[str]  # "stochastic" | "contextual" | "adversarial"

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @classmethod
    @abstractmethod
    def select(cls, *args, **kwargs):
        pass

    @classmethod
    @abstractmethod
    def train(cls, *args, **kwargs):
        pass

    @classmethod
    def build_state(cls, **params) -> BaseParamState:
        return cls.param_state_cls(**params)

    @classmethod
    def user_params(cls) -> list[PolicyParam]:
        result = []
        for name, field_info in cls.param_state_cls.model_fields.items():
            if not any(isinstance(m, _UserConfigurable) for m in field_info.metadata):
                continue

            constraints: dict[str, float] = {}
            for m in field_info.metadata:
                if hasattr(m, "gt") and m.gt is not None:
                    constraints["gt"] = m.gt
                if hasattr(m, "ge") and m.ge is not None:
                    constraints["gte"] = m.ge
                if hasattr(m, "lt") and m.lt is not None:
                    constraints["lt"] = m.lt
                if hasattr(m, "le") and m.le is not None:
                    constraints["lte"] = m.le

            default = field_info.default
            if default is PydanticUndefined:
                default = None

            # unwrap Annotated[T, ...] to get the base type for field_type resolution
            args = get_args(field_info.annotation)
            annotation = next(
                (a for a in args if a is not type(None)), field_info.annotation
            )
            field_type = "integer" if annotation is int else "number"

            result.append(
                PolicyParam(
                    name=name,
                    type=field_type,
                    required=field_info.is_required(),
                    default=default,
                    description=field_info.description or "",
                    constraints=constraints,
                )
            )

        return result
