"""names that reach outbound email, and the invite volume a workspace can send.

run against the real app and a real (sqlite) db, because every identity field
has to be refused on each path that can write it, not only at registration.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient

from qbrixstore.postgres.session import get_session

import proxysvc.config as _config_module
import proxysvc.mod.auth.operator as _op_module
from proxysvc.core.email import EmailService
from proxysvc.core.email import NullSender
from proxysvc.mod.auth.repository import TenantRepository
from proxysvc.mod.auth.repository import UserRepository
from proxysvc.mod.auth.scope import INVITES_PER_TENANT_PER_DAY

from svc.proxy.tests.conftest import RecordingSender

HOSTILE_NAMES = [
    "⚡TTam 70.000 TL bonus bit.ly/4q9lhYM⚡",
    "visit https://casino.example",
    "www.casino.example",
    "ｗｗｗ．casino．example",
    "line\nbreak",
    "x" * 65,
]


@pytest_asyncio.fixture
async def client(wired_app, monkeypatch) -> AsyncGenerator[AsyncClient, Any]:
    """non-dev, open signup, and no email provider so registrations auto-verify."""
    monkeypatch.setattr(_config_module.settings, "runenv", "test")
    monkeypatch.setattr(_config_module.settings, "signup_mode", "open")
    service = _op_module.auth_operator._service
    monkeypatch.setattr(service, "_signup_closed", False)
    monkeypatch.setattr(service, "_email", EmailService(NullSender()))
    transport = ASGITransport(app=wired_app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _record_mail(monkeypatch) -> RecordingSender:
    sender = RecordingSender()
    service = _op_module.auth_operator._service
    monkeypatch.setattr(service, "_email", EmailService(sender))
    return sender


async def _register(client: AsyncClient, email: str, **fields):
    return await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", **fields},
    )


async def _admin(client: AsyncClient, email: str = "owner@example.com") -> dict:
    registered = await _register(client, email, name="Owner", workspace_name="Acme")
    assert registered.status_code == 201, registered.text
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _invite(client: AsyncClient, headers: dict, email: str):
    return await client.post(
        "/api/auth/workspace/invites",
        json={"email": email, "role": "member"},
        headers=headers,
    )


def _assert_refused(response) -> None:
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "INVALID_IDENTITY"


class TestRegistrationRefusesHostileNames:
    @pytest.mark.parametrize("value", HOSTILE_NAMES)
    @pytest.mark.parametrize("field", ["name", "workspace_name"])
    async def test_is_422_and_creates_nothing(self, client, field, value):
        response = await _register(client, "bot@example.com", **{field: value})

        _assert_refused(response)
        service = _op_module.auth_operator._service
        assert await service.get_user_by_email("bot@example.com") is None

    @pytest.mark.parametrize("slug", ["Bad Slug", "a--b", "a_b", "x" * 65, "-"])
    async def test_a_malformed_slug_is_422(self, client, slug):
        _assert_refused(await _register(client, "bot@example.com", workspace_slug=slug))

    async def test_ordinary_names_are_trimmed_and_kept(self, client):
        response = await _register(
            client,
            "maria@example.com",
            name="  María José O'Neil  ",
            workspace_name="Acme Inc.",
            workspace_slug="acme-inc-",
        )

        assert response.status_code == 201, response.text
        assert response.json()["name"] == "María José O'Neil"
        service = _op_module.auth_operator._service
        user = await service.get_user_by_email("maria@example.com")
        workspace = await service.get_workspace(user["tenant_id"])
        assert workspace["name"] == "Acme Inc."
        assert workspace["slug"] == "acme-inc"

    async def test_a_colliding_slug_stays_within_the_column(self, client):
        slug = "a" * 64
        await _register(client, "one@example.com", workspace_slug=slug)
        await _register(client, "two@example.com", workspace_slug=slug)

        service = _op_module.auth_operator._service
        second = await service.get_user_by_email("two@example.com")
        workspace = await service.get_workspace(second["tenant_id"])
        assert workspace["slug"] == "a" * 62 + "-1"


class TestLaterWritesRefuseHostileNames:
    """a clean signup must not be able to rename itself into an ad afterwards."""

    async def test_profile_name(self, client):
        headers = await _admin(client)

        _assert_refused(
            await client.patch(
                "/api/auth/profile", json={"name": HOSTILE_NAMES[0]}, headers=headers
            )
        )

    async def test_workspace_name_and_slug(self, client):
        headers = await _admin(client)

        _assert_refused(
            await client.patch(
                "/api/auth/workspace",
                json={"name": HOSTILE_NAMES[0]},
                headers=headers,
            )
        )
        _assert_refused(
            await client.patch(
                "/api/auth/workspace", json={"slug": "Bad Slug"}, headers=headers
            )
        )

    async def test_invite_acceptance_name(self, client):
        headers = await _admin(client)
        invite = await _invite(client, headers, "colleague@example.com")

        _assert_refused(
            await client.post(
                f"/api/auth/invites/{invite.json()['token']}/accept",
                json={"password": "password123", "name": HOSTILE_NAMES[0]},
            )
        )


class TestInviteMailIsInert:
    """names written before validation existed still reach the invite email."""

    async def test_stored_markup_is_escaped_and_cannot_add_a_header(
        self, client, monkeypatch
    ):
        headers = await _admin(client)
        mailbox = _record_mail(monkeypatch)
        service = _op_module.auth_operator._service
        owner = await service.get_user_by_email("owner@example.com")
        async with get_session() as session:
            await UserRepository(session).update(
                owner["id"], name='<a href="https://x">⚡bonus⚡</a>'
            )
            await TenantRepository(session).update(
                owner["tenant_id"], name="Google\r\nBcc: victim@example.com"
            )

        response = await _invite(client, headers, "target@example.com")

        assert response.status_code == 201, response.text
        [(to, subject, html)] = mailbox.sent
        assert to == "target@example.com"
        assert "\r" not in subject and "\n" not in subject
        assert '<a href="https://x">' not in html
        assert "&lt;a href=&quot;https://x&quot;&gt;⚡bonus⚡&lt;/a&gt;" in html


class TestInviteDailyCap:
    async def test_revoke_and_reinvite_cannot_exceed_it(self, client):
        headers = await _admin(client)

        for _ in range(INVITES_PER_TENANT_PER_DAY):
            invite = await _invite(client, headers, "target@example.com")
            assert invite.status_code == 201, invite.text
            revoked = await client.delete(
                f"/api/auth/workspace/invites/{invite.json()['id']}",
                headers=headers,
            )
            assert revoked.status_code == 200, revoked.text

        refused = await _invite(client, headers, "target@example.com")

        assert refused.status_code == 429, refused.text
        assert refused.json()["code"] == "INVITE_LIMIT_EXCEEDED"
        assert 0 < int(refused.headers["Retry-After"]) <= 86400

    async def test_one_workspace_does_not_spend_anothers(self, client):
        first = await _admin(client, "first@example.com")
        for n in range(INVITES_PER_TENANT_PER_DAY):
            invite = await _invite(client, first, f"t{n}@example.com")
            await client.delete(
                f"/api/auth/workspace/invites/{invite.json()['id']}", headers=first
            )
        assert (await _invite(client, first, "more@example.com")).status_code == 429

        second = await _admin(client, "second@example.com")

        assert (await _invite(client, second, "more@example.com")).status_code == 201
