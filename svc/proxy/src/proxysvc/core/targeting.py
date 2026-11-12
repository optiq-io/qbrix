from __future__ import annotations

import hashlib
from typing import Any
from typing import Literal

Operator = Literal[
    "is",
    "is_not",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "gt",
    "gte",
    "lt",
    "lte",
]

OPERATORS: tuple[str, ...] = Operator.__args__


def holds(operator: Operator, actual: Any, expected: Any) -> bool:
    """whether actual stands in the operator's relation to expected. a
    comparison the values can't make is false, never an error."""
    try:
        match operator:
            case "is":
                return actual == expected
            case "is_not":
                return actual != expected
            case "in":
                return actual in expected
            case "not_in":
                return actual not in expected
            case "contains":
                return expected in actual
            case "not_contains":
                return expected not in actual
            case "gt":
                return actual > expected
            case "gte":
                return actual >= expected
            case "lt":
                return actual < expected
            case "lte":
                return actual <= expected
    except TypeError, AttributeError:
        return False
    raise ValueError(f"unknown operator: {operator}")


def bucket(identifier: str) -> int:
    """a stable bucket in 0..99 for an identifier, the same on every replica."""
    # builtin hash() is salted per process; blake2b is stable across processes
    digest = hashlib.blake2b(identifier.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 100
