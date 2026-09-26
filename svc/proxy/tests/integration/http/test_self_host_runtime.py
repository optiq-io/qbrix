"""self-host runtime: signup mode, the pre-auth config endpoint, auto-verify.

these run against the real fastapi app and a real (sqlite) db, because the
whole point of the signup mode is what the database already contains.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient

import proxysvc.config as _config_module
import proxysvc.mod.auth.operator as _op_module
from proxysvc.core.email import EmailService
from proxysvc.core.email import NullSender

from svc.proxy.tests.conftest import RecordingSender


@pytest_asyncio.fixture
async def public_client(wired_app, monkeypatch) -> AsyncGenerator[AsyncClient, Any]:
    """a client in non-dev mode, so registration is not auth-bypassed."""
    monkeypatch.setattr(_config_module.settings, "runenv", "test")
    transport = ASGITransport(app=wired_app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _signup_mode(monkeypatch, mode: str) -> None:
    monkeypatch.setattr(_config_module.settings, "signup_mode", mode)
    _op_module.auth_operator._service._signup_closed = False


async def _register(client: AsyncClient, email: str):
    return await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "name": "Someone",
            "workspace_name": "Acme",
            "workspace_slug": email.split("@")[0],
        },
    )


class TestSignupMode:
    async def test_first_user_creates_the_workspace_then_closes(
        self, public_client, monkeypatch
    ):
        _signup_mode(monkeypatch, "first-user")

        first = await _register(public_client, "founder@example.com")
        assert first.status_code == 201
        assert first.json()["role"] == "admin"

        second = await _register(public_client, "stranger@example.com")
        assert second.status_code == 403
        assert second.json()["code"] == "SIGNUP_CLOSED"

    async def test_open_accepts_every_registration(self, public_client, monkeypatch):
        _signup_mode(monkeypatch, "open")

        assert (await _register(public_client, "one@example.com")).status_code == 201
        assert (await _register(public_client, "two@example.com")).status_code == 201

    async def test_invite_only_refuses_the_very_first_registration(
        self, public_client, monkeypatch
    ):
        _signup_mode(monkeypatch, "invite-only")

        response = await _register(public_client, "founder@example.com")

        assert response.status_code == 403
        assert response.json()["code"] == "SIGNUP_CLOSED"

    @pytest.mark.parametrize("mode", ["open", "first-user", "invite-only"])
    async def test_invite_acceptance_works_in_every_mode(
        self, public_client, monkeypatch, mode
    ):
        _signup_mode(monkeypatch, "open")
        await _register(public_client, "founder@example.com")

        service = _op_module.auth_operator._service
        admin = await service.get_user_by_email("founder@example.com")
        invite = await service.create_invite(
            tenant_id=admin["tenant_id"],
            email="colleague@example.com",
            role="member",
            invited_by=admin["id"],
        )

        _signup_mode(monkeypatch, mode)
        response = await public_client.post(
            f"/api/auth/invites/{invite['token']}/accept",
            json={"password": "password123", "name": "Colleague"},
        )

        assert response.status_code == 201
        assert response.json()["email"] == "colleague@example.com"


class TestAuthConfig:
    async def test_needs_no_auth_and_answers_three_fields(
        self, public_client, monkeypatch
    ):
        _signup_mode(monkeypatch, "open")

        response = await public_client.get("/api/auth/config")

        assert response.status_code == 200
        assert response.json() == {
            "signup_open": True,
            "edition": _op_module.auth_operator.entitlements.edition,
            "email_enabled": True,
        }

    async def test_tracks_first_user_closing_signup(self, public_client, monkeypatch):
        _signup_mode(monkeypatch, "first-user")

        assert (await public_client.get("/api/auth/config")).json()["signup_open"]

        await _register(public_client, "founder@example.com")

        assert not (await public_client.get("/api/auth/config")).json()["signup_open"]

    async def test_reports_a_deployment_without_email(self, public_client, monkeypatch):
        service = _op_module.auth_operator._service
        monkeypatch.setattr(service, "_email", EmailService(NullSender()))

        assert (await public_client.get("/api/auth/config")).json()[
            "email_enabled"
        ] is False


class TestAutoVerify:
    async def test_no_provider_lets_the_new_user_sign_in_immediately(
        self, public_client, monkeypatch
    ):
        _signup_mode(monkeypatch, "open")
        service = _op_module.auth_operator._service
        monkeypatch.setattr(service, "_email", EmailService(NullSender()))

        registered = await _register(public_client, "solo@example.com")
        assert registered.status_code == 201
        assert registered.json()["email_verified"] is True

        login = await public_client.post(
            "/api/auth/login",
            json={"email": "solo@example.com", "password": "password123"},
        )
        assert login.status_code == 200

    async def test_a_configured_provider_still_requires_verification(
        self, public_client, monkeypatch
    ):
        _signup_mode(monkeypatch, "open")
        sender = RecordingSender()
        service = _op_module.auth_operator._service
        monkeypatch.setattr(service, "_email", EmailService(sender))

        registered = await _register(public_client, "solo@example.com")
        assert registered.json()["email_verified"] is False

        login = await public_client.post(
            "/api/auth/login",
            json={"email": "solo@example.com", "password": "password123"},
        )
        assert login.status_code == 403
        assert len(sender.sent) == 1
