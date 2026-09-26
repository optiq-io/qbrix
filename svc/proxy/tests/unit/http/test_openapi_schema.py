"""unit tests for the proxysvc openapi schema customizations.

invariants verified:
  - agent select/feedback routes expose typed response models
  - the {code, detail, context} error envelope is a registered component schema
  - the ErrorCode enum covers every BaseAPIException subclass code
  - standard 4xx/5xx error responses are attached app-wide without clobbering
    existing success / validation responses
"""

from __future__ import annotations

import inspect

import pytest

from proxysvc.transport.http import exception as exc_module
from proxysvc.transport.http.exception import BaseAPIException

_STANDARD_ERROR_CODES = {"400", "401", "403", "404", "409", "429", "500", "503"}


@pytest.fixture
def schema() -> dict:
    """build a fresh openapi schema (bypass the module-level cache)."""
    from proxysvc.transport.http.app import app

    app.openapi_schema = None
    return app.openapi()


def _all_exception_codes() -> set[str]:
    codes: set[str] = set()
    for _, obj in inspect.getmembers(exc_module, inspect.isclass):
        if issubclass(obj, BaseAPIException):
            codes.add(obj.code)
    return codes


def test_agent_routes_expose_typed_responses(schema: dict) -> None:
    schemas = schema["components"]["schemas"]
    assert "AgentSelectResponse" in schemas
    assert "AgentFeedbackResponse" in schemas

    select = schema["paths"]["/api/v1/agent/select"]["post"]
    feedback = schema["paths"]["/api/v1/agent/feedback"]["post"]

    assert select["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgentSelectResponse"
    }
    assert feedback["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgentFeedbackResponse"
    }


def test_agent_select_response_shape(schema: dict) -> None:
    """select response is exactly {arm, request_id, is_default} — no learner_* leak."""
    model = schema["components"]["schemas"]["AgentSelectResponse"]
    assert set(model["properties"]) == {"arm", "request_id", "is_default"}


def test_error_response_schema_registered(schema: dict) -> None:
    schemas = schema["components"]["schemas"]
    assert "ErrorResponse" in schemas
    assert "ErrorCode" in schemas

    props = schemas["ErrorResponse"]["properties"]
    assert set(props) >= {"code", "detail", "context"}
    assert set(schemas["ErrorResponse"]["required"]) == {"code", "detail"}


def test_error_code_enum_covers_all_exception_codes(schema: dict) -> None:
    enum_codes = set(schema["components"]["schemas"]["ErrorCode"]["enum"])
    assert enum_codes == _all_exception_codes()


def test_standard_errors_attached_without_clobbering(schema: dict) -> None:
    select = schema["paths"]["/api/v1/agent/select"]["post"]
    responses = select["responses"]

    # all standard error codes present and referencing ErrorResponse
    assert _STANDARD_ERROR_CODES <= set(responses)
    for code in _STANDARD_ERROR_CODES:
        assert responses[code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }

    # existing success + validation responses are preserved
    assert "200" in responses
    assert "422" in responses
