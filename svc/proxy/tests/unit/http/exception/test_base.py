"""unit tests for BaseAPIException code and to_dict() shape."""

from __future__ import annotations

import inspect

import pytest

from proxysvc.transport.http import exception as exc_module
from proxysvc.transport.http.exception import BaseAPIException
from proxysvc.transport.http.exception import PoolHasExperimentsException


def _all_exception_classes() -> list[type[BaseAPIException]]:
    classes: list[type[BaseAPIException]] = []
    for _, obj in inspect.getmembers(exc_module, inspect.isclass):
        if issubclass(obj, BaseAPIException):
            classes.append(obj)
    return classes


def test_every_exception_subclass_declares_non_empty_code():
    for cls in _all_exception_classes():
        assert isinstance(cls.code, str), f"{cls.__name__} missing code"
        assert cls.code.strip(), f"{cls.__name__} has empty code"
        assert (
            cls.code == cls.code.upper()
        ), f"{cls.__name__} code must be upper snake: {cls.code}"


def test_codes_are_unique_across_subclasses():
    seen: dict[str, str] = {}
    for cls in _all_exception_classes():
        if cls is BaseAPIException:
            continue
        assert (
            cls.code not in seen or seen[cls.code] == cls.__name__
        ), f"duplicate code {cls.code} on {cls.__name__} and {seen[cls.code]}"
        seen[cls.code] = cls.__name__


def test_to_dict_includes_code_and_detail():
    exc = PoolHasExperimentsException()
    body = exc.to_dict()
    assert body["code"] == "POOL_HAS_EXPERIMENTS"
    assert body["detail"] == PoolHasExperimentsException.detail
    assert "context" not in body


def test_to_dict_includes_context_when_provided():
    exc = PoolHasExperimentsException(context={"pool_id": "p-1", "count": 2})
    body = exc.to_dict()
    assert body["code"] == "POOL_HAS_EXPERIMENTS"
    assert body["context"] == {"pool_id": "p-1", "count": 2}


def test_custom_detail_overrides_default():
    exc = PoolHasExperimentsException(detail="custom message")
    assert exc.to_dict()["detail"] == "custom message"
    assert exc.to_dict()["code"] == "POOL_HAS_EXPERIMENTS"


@pytest.mark.parametrize(
    "name,expected_code",
    [
        ("PoolNotFoundException", "POOL_NOT_FOUND"),
        ("ExperimentLimitException", "EXPERIMENT_LIMIT_REACHED"),
        ("APIKeyLimitException", "API_KEY_LIMIT_REACHED"),
        ("InvalidPolicyParamsException", "INVALID_POLICY_PARAMS"),
        ("LearnerExperimentDeleteException", "LEARNER_EXPERIMENT_DELETE_FORBIDDEN"),
        ("RateLimitedException", "RATE_LIMITED"),
        ("InsufficientScopesException", "INSUFFICIENT_SCOPES"),
        ("InvalidTokenException", "INVALID_TOKEN"),
        ("UserAlreadyExistsException", "USER_ALREADY_EXISTS"),
    ],
)
def test_known_codes(name: str, expected_code: str):
    cls = getattr(exc_module, name)
    assert cls.code == expected_code
