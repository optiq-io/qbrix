"""unit tests for the scoped cors policy.

preflight never reaches a route handler — CORSMiddleware short-circuits it — so
the real app can be exercised here without any database or redis wiring. simple
responses are asserted against a minimal app carrying the same policies.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from httpx import AsyncClient

from proxysvc.config import ProxySettings
from proxysvc.transport.http.constant import AGENT_PATH_PREFIX
from proxysvc.transport.http.cors import AGENT_CORS_POLICY
from proxysvc.transport.http.cors import AGENT_CORS_PREFIXES
from proxysvc.transport.http.cors import DEFAULT_CORS_POLICY
from proxysvc.transport.http.cors import LOCALHOST_ORIGINS
from proxysvc.transport.http.cors import console_origins
from proxysvc.transport.http.cors import ScopedCORSMiddleware

FOREIGN_ORIGIN = "https://shop.customer.example"
CONSOLE_ORIGIN = "http://localhost:3001"

AGENT_SELECT = "/api/v1/agent/select"
AGENT_FEEDBACK = "/api/v1/agent/feedback"
MANAGEMENT = "/api/v1/experiments"


def _preflight_headers(origin: str, method: str = "POST", request_headers: str = ""):
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": method,
    }
    if request_headers:
        headers["Access-Control-Request-Headers"] = request_headers
    return headers


@pytest.fixture
def real_app():
    from proxysvc.transport.http.app import app

    return app


@pytest.fixture
def scoped_app():
    """minimal app wearing the same scoped cors policy as the real one."""
    app = FastAPI()

    @app.post(AGENT_SELECT)
    async def select() -> dict:
        return {"ok": True}

    @app.post(MANAGEMENT)
    async def experiments() -> dict:
        return {"ok": True}

    @app.post("/api/v1/agentless")
    async def agentless() -> dict:
        return {"ok": True}

    app.add_middleware(
        ScopedCORSMiddleware,
        scoped_prefixes=AGENT_CORS_PREFIXES,
        scoped_policy=AGENT_CORS_POLICY,
        default_policy=DEFAULT_CORS_POLICY,
    )
    return app


async def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── preflight, against the real application ───────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("path", [AGENT_SELECT, AGENT_FEEDBACK])
async def test_agent_preflight_allows_any_origin_without_credentials(real_app, path):
    async with await _client(real_app) as client:
        response = await client.options(
            path, headers=_preflight_headers(FOREIGN_ORIGIN)
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.unit
async def test_agent_preflight_permits_the_api_key_header(real_app):
    async with await _client(real_app) as client:
        response = await client.options(
            AGENT_SELECT,
            headers=_preflight_headers(
                FOREIGN_ORIGIN, request_headers="x-api-key,content-type"
            ),
        )

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "x-api-key" in allowed
    assert "content-type" in allowed


@pytest.mark.unit
async def test_management_preflight_rejects_a_foreign_origin(real_app):
    async with await _client(real_app) as client:
        response = await client.options(
            MANAGEMENT, headers=_preflight_headers(FOREIGN_ORIGIN)
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.unit
async def test_management_preflight_still_serves_the_console_with_credentials(real_app):
    async with await _client(real_app) as client:
        response = await client.options(
            MANAGEMENT, headers=_preflight_headers(CONSOLE_ORIGIN)
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == CONSOLE_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.unit
async def test_agent_preflight_is_cached_longer_than_the_default(real_app):
    async with await _client(real_app) as client:
        agent = await client.options(
            AGENT_SELECT, headers=_preflight_headers(FOREIGN_ORIGIN)
        )
        management = await client.options(
            MANAGEMENT, headers=_preflight_headers(CONSOLE_ORIGIN)
        )

    assert int(agent.headers["access-control-max-age"]) > int(
        management.headers["access-control-max-age"]
    )


# ── simple responses, against a minimal app ───────────────────────────────────


@pytest.mark.unit
async def test_agent_response_carries_the_wildcard_origin(scoped_app):
    async with await _client(scoped_app) as client:
        response = await client.post(AGENT_SELECT, headers={"Origin": FOREIGN_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.unit
async def test_agent_response_exposes_retry_after(scoped_app):
    async with await _client(scoped_app) as client:
        response = await client.post(AGENT_SELECT, headers={"Origin": FOREIGN_ORIGIN})

    assert "Retry-After" in response.headers["access-control-expose-headers"]


@pytest.mark.unit
async def test_management_response_withholds_a_foreign_origin(scoped_app):
    async with await _client(scoped_app) as client:
        response = await client.post(MANAGEMENT, headers={"Origin": FOREIGN_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.unit
async def test_a_path_merely_prefixed_by_agent_keeps_the_strict_policy(scoped_app):
    """/api/v1/agentless must not inherit the wildcard — the prefix ends in a slash."""
    async with await _client(scoped_app) as client:
        response = await client.post(
            "/api/v1/agentless", headers={"Origin": FOREIGN_ORIGIN}
        )

    assert "access-control-allow-origin" not in response.headers


@pytest.mark.unit
def test_the_agent_prefix_matches_the_mounted_router():
    assert AGENT_SELECT.startswith(AGENT_PATH_PREFIX)
    assert AGENT_FEEDBACK.startswith(AGENT_PATH_PREFIX)
    assert not MANAGEMENT.startswith(AGENT_PATH_PREFIX)


# ── configurable console origins ──────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "configured,expected",
    [
        ("", []),
        ("https://qbrix.acme.internal", ["https://qbrix.acme.internal"]),
        (
            " https://a.example , https://b.example ",
            ["https://a.example", "https://b.example"],
        ),
        ("https://a.example,,", ["https://a.example"]),
    ],
)
def test_configured_origins_extend_localhost(configured, expected):
    origins = console_origins(ProxySettings(cors_origins=configured))

    assert origins == LOCALHOST_ORIGINS + expected


@pytest.mark.unit
async def test_a_configured_origin_gets_credentialed_headers_and_others_do_not():
    policy = {
        **DEFAULT_CORS_POLICY,
        "allow_origins": console_origins(
            ProxySettings(cors_origins="https://qbrix.acme.internal")
        ),
    }
    app = FastAPI()

    @app.post(MANAGEMENT)
    async def experiments() -> dict:
        return {"ok": True}

    app.add_middleware(
        ScopedCORSMiddleware,
        scoped_prefixes=AGENT_CORS_PREFIXES,
        scoped_policy=AGENT_CORS_POLICY,
        default_policy=policy,
    )

    async with await _client(app) as client:
        allowed = await client.post(
            MANAGEMENT, headers={"Origin": "https://qbrix.acme.internal"}
        )
        denied = await client.post(MANAGEMENT, headers={"Origin": FOREIGN_ORIGIN})

    assert (
        allowed.headers["access-control-allow-origin"] == "https://qbrix.acme.internal"
    )
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in denied.headers
