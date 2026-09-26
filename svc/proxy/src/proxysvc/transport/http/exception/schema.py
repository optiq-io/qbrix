from __future__ import annotations

from enum import Enum
from typing import Any
from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from proxysvc.transport.http.exception.base import BaseAPIException


def _collect_error_codes() -> dict[str, str]:
    """collect stable codes from every BaseAPIException subclass, recursively.

    walking __subclasses__() keeps this in sync with exception/base.py — adding a
    new exception with a new code surfaces it in the openapi schema automatically.
    """
    codes: dict[str, str] = {BaseAPIException.code: BaseAPIException.code}

    def walk(cls: type[BaseAPIException]) -> None:
        for sub in cls.__subclasses__():
            codes[sub.code] = sub.code
            walk(sub)

    walk(BaseAPIException)
    return codes


# str-valued enum so openapi renders a string enum and pydantic serializes to the value
ErrorCode = Enum("ErrorCode", _collect_error_codes(), type=str)


class ErrorResponse(BaseModel):
    """standard error envelope rendered by the BaseAPIException handler."""

    code: ErrorCode = Field(
        ..., description="stable upper-snake error identifier for client mapping"
    )
    detail: str = Field(..., description="human-readable error message")
    context: Optional[dict[str, Any]] = Field(
        default=None, description="optional structured error context"
    )
