"""the http api's handler for BaseAPIException: a client error is an expected
outcome, so only a server error may reach the error log."""

from __future__ import annotations

import json
import logging

import pytest
from starlette.requests import Request

from proxysvc.transport.http.exception import BaseAPIException
from proxysvc.transport.http.exception import SignupClosedException


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


@pytest.fixture
def handler():
    from proxysvc.transport.http.app import handle_api_exception

    return handle_api_exception


async def test_a_client_error_is_not_logged_as_an_error(handler, caplog):
    caplog.set_level(logging.INFO, logger="proxysvc.transport.http.app")

    response = await handler(_request("/api/auth/register"), SignupClosedException())

    assert response.status_code == 403
    assert json.loads(response.body)["code"] == "SIGNUP_CLOSED"
    records = [r for r in caplog.records if r.name == "proxysvc.transport.http.app"]
    assert [r.levelno for r in records] == [logging.INFO]


async def test_a_server_error_is_logged_as_an_error(handler, caplog):
    caplog.set_level(logging.INFO, logger="proxysvc.transport.http.app")

    response = await handler(_request("/api/v1/pools"), BaseAPIException())

    assert response.status_code == 500
    records = [r for r in caplog.records if r.name == "proxysvc.transport.http.app"]
    assert [r.levelno for r in records] == [logging.ERROR]
