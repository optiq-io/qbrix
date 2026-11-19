"""integration tests for the workspace webhook, a qbrix next surface.

invariants verified:
  an admin sets the url and gets the signing secret once: no later read
  carries it and the database holds only its sealed form. replacing the url
  keeps the secret; regenerating replaces it, and the next send signs with the
  new one. a test send is signed so the receiver can recompute the signature
  over the raw body, and is kept as a delivery naming who sent it; the read
  shows the newest five. the cloud refuses a url that isn't public https, on
  save and at send; a self-hosted install takes any http(s) url. members and
  viewers read whether it is configured and its deliveries, never the whole
  url or the secret, and can't write; an api key and a connection's token
  can't either. a secret sealed under another box key fails the send, which
  never goes out unsigned. removing it clears its deliveries. none of it is a
  change, the inbox says whether one is configured, and another workspace
  never sees it.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func
from sqlalchemy import select

import proxysvc.config
from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User
from qbrixstore.postgres.models import Webhook
from qbrixstore.postgres.models import WebhookDelivery
from qbrixstore.postgres.session import get_session

from proxysvc.core.actor import Actor
from proxysvc.mod.webhook.sender import WebhookSender
from proxysvc.mod.webhook.service import UNREADABLE
from proxysvc.mod.webhook.service import WebhookService
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
OTHER_TENANT = "other-tenant"
ADA = "user-ada"
BEN = "user-ben"
PUBLIC = "93.184.216.34"
SLACK = "https://hooks.slack.com/services/T0/B0/abcdef"
START = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)


class _Receiver:
    """the other end of the webhook: records each request, answers status."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.status = 200

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, text="ok")

        return httpx.MockTransport(handle)


class _Edition:
    def __init__(self, edition: str):
        self.edition = edition


def _resolver(table: dict[str, str]):
    async def resolve(host: str) -> list[str]:
        return [table.get(host, PUBLIC)]

    return resolve


def _service(wired_app, receiver: _Receiver, *, edition="cloud", box_key=None):
    settings = wired_app.svc._settings
    if box_key is not None:
        settings = settings.model_copy(update={"secret_box_key": box_key})
    ticks = itertools.count()
    return WebhookService(
        settings=settings,
        entitlements=_Edition(edition),
        sender=WebhookSender(
            resolver=_resolver({"inward.example": "192.168.1.4"}),
            transport=receiver.transport(),
        ),
        clock=lambda: START + timedelta(seconds=next(ticks)),
    )


@pytest_asyncio.fixture
async def receiver(wired_app, next_enabled) -> _Receiver:
    receiver = _Receiver()
    wired_app.svc._webhook_service = _service(wired_app, receiver)
    return receiver


@pytest_asyncio.fixture
async def api(wired_app, client, receiver):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    async with get_session() as session:
        session.add(Tenant(id=TENANT, name="Acme", slug="acme"))
        session.add(Tenant(id=OTHER_TENANT, name="Other", slug="other"))
        for user_id, name in ((ADA, "Ada"), (BEN, "Ben")):
            session.add(
                User(
                    id=user_id,
                    tenant_id=TENANT,
                    email=f"{user_id}@example.com",
                    password_hash="x",
                    name=name,
                )
            )
    with as_tenant(app, tenant_id=TENANT, user_id=ADA, role="admin"):
        yield client
    app.router.routes[:] = routes


def _verifies(request: httpx.Request, secret: str) -> bool:
    parts = dict(p.split("=", 1) for p in request.headers["qbrix-signature"].split(","))
    expected = hmac.new(
        secret.encode(), f"{parts['t']}.".encode() + request.content, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])


async def _set(api, url: str = SLACK) -> dict:
    resp = await api.put("/api/v1/webhook", json={"url": url})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def _read(api, **params) -> dict:
    resp = await api.get("/api/v1/webhook", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _test(api) -> dict:
    resp = await api.post("/api/v1/webhook/test")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _stored() -> Webhook:
    async with get_session() as session:
        return (await session.execute(select(Webhook))).scalar_one()


class TestSecret:
    async def test_shown_once_and_stored_only_sealed(self, api):
        resp = await api.put("/api/v1/webhook", json={"url": SLACK})

        assert resp.status_code == 201
        made = resp.json()
        secret = made["secret"]
        assert secret.startswith("whsec_")
        assert made["secret_hint"] == secret[-4:]
        assert made["configured"] is True
        assert made["url_masked"] == "https://hooks.slack.com/…"

        read = await _read(api)
        assert "secret" not in read
        assert secret not in json.dumps(read)
        stored = await _stored()
        assert stored.secret_ciphertext.startswith("v1.")
        assert secret not in stored.secret_ciphertext

    async def test_replacing_the_url_keeps_the_secret(self, api, receiver):
        secret = (await _set(api))["secret"]

        resp = await api.put(
            "/api/v1/webhook", json={"url": "https://hooks.example/other"}
        )

        assert resp.status_code == 200
        assert "secret" not in resp.json()
        assert (await _test(api))["status"] == "delivered"
        assert str(receiver.requests[-1].url).endswith("/other")
        assert _verifies(receiver.requests[-1], secret)

    async def test_regenerating_signs_the_next_send_with_the_new_one(
        self, api, receiver
    ):
        old = (await _set(api))["secret"]

        resp = await api.post("/api/v1/webhook/secret")

        assert resp.status_code == 200
        new = resp.json()["secret"]
        assert new != old
        assert resp.json()["secret_hint"] == new[-4:]
        assert "secret" not in await _read(api)
        await _test(api)
        assert _verifies(receiver.requests[-1], new)
        assert not _verifies(receiver.requests[-1], old)

    async def test_another_box_key_fails_the_send_and_sends_nothing(
        self, wired_app, api, receiver
    ):
        await _set(api)
        wired_app.svc._webhook_service = _service(
            wired_app, receiver, box_key="a-rotated-secret-box-key-of-32-chars-or-more"
        )

        sent = await _test(api)

        assert sent["status"] == "failed"
        assert sent["last_error"] == UNREADABLE
        assert receiver.requests == []
        assert (await _read(api))["deliveries"][0]["last_error"] == UNREADABLE


class TestTestSend:
    async def test_carries_a_text_line_and_a_signature_the_receiver_checks(
        self, api, receiver
    ):
        secret = (await _set(api))["secret"]

        sent = await _test(api)

        (request,) = receiver.requests
        body = json.loads(request.content)
        assert body["text"] == "Test from Ada · qbrix"
        assert body["kind"] == "test"
        assert body["workspace"] == {"name": "Acme"}
        assert _verifies(request, secret)
        assert request.headers["qbrix-delivery"] == sent["id"]
        assert request.headers["host"] == "hooks.slack.com"
        assert sent["status"] == "delivered"
        assert sent["summary"] == "Test from Ada · qbrix"
        assert sent["sent_by"] == {"id": ADA, "name": "Ada"}
        assert sent["results"][0]["status_code"] == 200

    async def test_a_failing_receiver_is_kept_with_its_status(self, api, receiver):
        await _set(api)
        receiver.status = 502

        sent = await _test(api)

        assert sent["status"] == "failed"
        assert sent["last_status_code"] == 502
        assert sent["last_error"] == "answered 502"

    async def test_the_read_shows_the_newest_five(self, wired_app, api):
        await _set(api)
        for _ in range(4):
            await _test(api)
        with as_tenant(wired_app.app, tenant_id=TENANT, user_id=BEN, role="admin"):
            newest = [await _test(api) for _ in range(3)]

        deliveries = (await _read(api))["deliveries"]

        assert len(deliveries) == 5
        assert [d["id"] for d in deliveries[:3]] == [d["id"] for d in newest[::-1]]
        assert [d["sent_by"]["name"] for d in deliveries] == ["Ben"] * 3 + ["Ada"] * 2

    async def test_needs_a_webhook(self, api):
        resp = await api.post("/api/v1/webhook/test")

        assert resp.status_code == 404
        assert resp.json()["code"] == "WEBHOOK_NOT_FOUND"


class TestURLRule:
    @pytest.mark.parametrize(
        "url",
        [
            "http://hooks.example/x",
            "https://10.0.0.5/",
            "https://inward.example/x",
        ],
    )
    async def test_the_cloud_refuses_what_isnt_public_https(self, api, url):
        resp = await api.put("/api/v1/webhook", json={"url": url})

        assert resp.status_code == 422
        assert resp.json()["code"] == "INVALID_WEBHOOK_URL"

    @pytest.mark.parametrize(
        "url",
        [
            "http://hooks.example/x",
            "https://10.0.0.5/",
            "https://inward.example/x",
        ],
    )
    async def test_self_hosted_takes_any_http_url(self, wired_app, api, receiver, url):
        wired_app.svc._webhook_service = _service(wired_app, receiver, edition="oss")

        await _set(api, url)

        assert (await _test(api))["status"] == "delivered"
        assert str(receiver.requests[-1].url) == url

    async def test_the_cloud_checks_again_at_send(self, wired_app, api, receiver):
        await _set(api)
        async with get_session() as session:
            stored = (await session.execute(select(Webhook))).scalar_one()
            stored.url = "https://inward.example/x"

        sent = await _test(api)

        assert sent["status"] == "failed"
        assert "public internet" in sent["last_error"]
        assert receiver.requests == []


class TestRoles:
    @pytest.mark.parametrize("role", ["member", "viewer"])
    async def test_reads_but_never_writes_or_reveals(self, wired_app, api, role):
        await _set(api)
        await _test(api)

        with as_tenant(wired_app.app, tenant_id=TENANT, user_id=BEN, role=role):
            read = await _read(api)
            revealed = await api.get("/api/v1/webhook", params={"reveal": "true"})
            writes = [
                await api.put("/api/v1/webhook", json={"url": SLACK}),
                await api.post("/api/v1/webhook/secret"),
                await api.post("/api/v1/webhook/test"),
                await api.delete("/api/v1/webhook"),
            ]

        assert read["configured"] is True
        assert len(read["deliveries"]) == 1
        assert "url" not in read and "secret" not in read
        assert revealed.status_code == 403
        assert [w.status_code for w in writes] == [403] * 4

    async def test_an_admin_reveals_the_whole_url(self, api):
        await _set(api)

        assert (await _read(api, reveal="true"))["url"] == SLACK
        assert "url" not in await _read(api)

    async def test_an_api_key_is_refused(self, wired_app, api):
        await _set(api)
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member(ADA, api_key_id="key-1")
        try:
            writes = [
                await api.put("/api/v1/webhook", json={"url": SLACK}),
                await api.post("/api/v1/webhook/secret"),
                await api.post("/api/v1/webhook/test"),
                await api.delete("/api/v1/webhook"),
            ]
        finally:
            del overrides[get_actor]

        assert [w.status_code for w in writes] == [403] * 4

    async def test_a_connections_token_is_refused(self, wired_app, api, monkeypatch):
        issued = await wired_app.svc.connections.open(
            user_id=ADA,
            tenant_id=TENANT,
            client_identity="Claude Code:ada",
            client_id="client-claude",
            client_name="Claude Code",
            client_uri=None,
            resource=wired_app.svc._settings.mcp_resource,
        )
        app = wired_app.app
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        monkeypatch.setattr(proxysvc.config.settings, "runenv", "prod")
        headers = {"Authorization": f"Bearer {issued.access_token}"}
        try:
            writes = [
                await api.put("/api/v1/webhook", json={"url": SLACK}, headers=headers),
                await api.post("/api/v1/webhook/secret", headers=headers),
                await api.post("/api/v1/webhook/test", headers=headers),
                await api.delete("/api/v1/webhook", headers=headers),
            ]
        finally:
            app.dependency_overrides.update(saved)

        assert [w.status_code for w in writes] == [401] * 4
        async with get_session() as session:
            count = await session.execute(select(func.count()).select_from(Webhook))
            assert count.scalar_one() == 0


class TestRemove:
    async def test_clears_the_webhook_and_its_deliveries(self, api):
        await _set(api)
        await _test(api)

        resp = await api.delete("/api/v1/webhook")

        assert resp.status_code == 204
        assert await _read(api) == {"configured": False, "deliveries": []}
        async with get_session() as session:
            count = await session.execute(
                select(func.count()).select_from(WebhookDelivery)
            )
            assert count.scalar_one() == 0
        assert (await api.delete("/api/v1/webhook")).status_code == 404

    async def test_a_new_webhook_gets_a_new_secret(self, api):
        first = (await _set(api))["secret"]
        await api.delete("/api/v1/webhook")

        assert (await _set(api))["secret"] != first


class TestSetting:
    async def test_nothing_is_a_change(self, api):
        await _set(api)
        await api.post("/api/v1/webhook/secret")
        await _test(api)
        await api.delete("/api/v1/webhook")

        async with get_session() as session:
            count = await session.execute(select(func.count()).select_from(Change))
            assert count.scalar_one() == 0

    async def test_the_inbox_says_whether_one_is_configured(self, api):
        before = (await api.get("/api/v1/inbox")).json()
        await _set(api)
        after = (await api.get("/api/v1/inbox")).json()

        assert before["webhook"] == {"configured": False}
        assert after["webhook"] == {"configured": True}

    async def test_another_workspace_never_sees_it(self, wired_app, api):
        await _set(api)
        await _test(api)

        with as_tenant(wired_app.app, tenant_id=OTHER_TENANT, user_id=BEN):
            read = await _read(api)
            inbox = (await api.get("/api/v1/inbox")).json()

        assert read == {"configured": False, "deliveries": []}
        assert inbox["webhook"] == {"configured": False}
