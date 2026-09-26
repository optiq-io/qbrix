from typing import Annotated
from typing import TypeVar
from typing import Any
import numpy as np
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

T = TypeVar("T")


class _ArrayParamAnnotation:

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda v: v.tolist(),
                info_arg=False,
            ),
        )

    @staticmethod
    def _validate(v: Any) -> np.ndarray:
        if isinstance(v, np.ndarray):
            return v
        if isinstance(v, (list, tuple)):
            return np.array(v)
        raise ValueError(f"Cannot convert {type(v)} to numpy array")


ArrayParam = Annotated[np.ndarray, _ArrayParamAnnotation()]


class _UserConfigurable:
    """marker for user-configurable policy parameters."""


UserConfigurable = Annotated[T, _UserConfigurable()]
