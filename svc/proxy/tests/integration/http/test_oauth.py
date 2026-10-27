"""integration tests for signing connections in over oauth 2.1, a qbrix next surface.

invariants verified:
  a client that registers itself and a client identified by a metadata
  document each complete authorize, approval and token, and get an access and
  a refresh token; every redirect back carries iss and state. a request
  without S256 pkce, for another resource or scope, or with an unregistered
  redirect uri is refused, and a code works once, for its client, redirect uri
  and verifier only. signing in again renews the connection. a refresh rotates
  both tokens, and presenting a used refresh token revokes the connection. a
  connection unused for 90 days can't refresh. a token is accepted only for
  this server's /mcp, as an access token, while unexpired, unrevoked and its
  person active, and carries the person's role as it is now. each connection
  has its own request limit. people list and revoke their own connections,
  admins all in their workspace, and an api key can't reach any of it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import update

import proxysvc.config
from qbrixstore.postgres import session as session_module
from qbrixstore.postgres.models import Connection
from qbrixstore.postgres.models import ConnectionToken
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User

from proxysvc.core.actor import Actor
from proxysvc.core.error import ConnectionRateLimitedError
from proxysvc.core.error import ConnectionTokenInvalidError
from proxysvc.mod.oauth.cimd import CIMDFetcher
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"
REDIRECT = "http://127.0.0.1/callback"
DOC_URL = "https://client.example/oauth/metadata.json"
DOC_REDIRECT = "https://client.example/callback"
DOC_ADDRESS = "93.184.216.34"

PEOPLE = {
    "user-admin": (TENANT, "admin"),
    "user-member": (TENANT, "member"),
    "user-viewer": (TENANT, "viewer"),
    "user-b": (OTHER_TENANT, "admin"),
}


def _document_transport() -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == DOC_ADDRESS
        assert request.headers["host"] == "client.example"
        return httpx.Response(
            200,
            json={
                "client_id": DOC_URL,
                "client_name": "Doc Client",
                "client_uri": "https://client.example",
                "redirect_uris": [DOC_REDIRECT],
            },
        )

    return httpx.MockTransport(handle)


async def _public_resolver(host: str) -> list[str]:
    return [DOC_ADDRESS]


@pytest_asyncio.fixture
async def oauth(wired_app, client, next_enabled):
    """the client, with the next routes mounted, two workspaces of people, and
    a metadata document served from the public internet."""
    async with session_module.get_session() as session:
        for tenant in (TENANT, OTHER_TENANT):
            session.add(Tenant(id=tenant, name=tenant, slug=tenant))
        for user_id, (tenant, role) in PEOPLE.items():
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant,
                    email=f"{user_id}@example.com",
                    password_hash="x",
                    name=user_id,
                    role=role,
                )
            )

    svc = wired_app.svc
    svc._cimd = CIMDFetcher(resolver=_public_resolver, transport=_document_transport())
    svc._build_services()

    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    yield client
    app.router.routes[:] = routes


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _resource(wired_app) -> str:
    return wired_app.svc._settings.mcp_resource


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


async def _register(client, **overrides) -> str:
    body = {"client_name": "Claude Code", "redirect_uris": [REDIRECT], **overrides}
    resp = await client.post("/oauth/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["client_id"]


async def _authorize(client, wired_app, client_id, challenge, **overrides):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": _resource(wired_app),
        "scope": "qbrix",
        "state": "st-1",
        **overrides,
    }
    return await client.get(
        "/oauth/authorize", params={k: v for k, v in params.items() if v is not None}
    )


async def _approve(client, wired_app, location, user="user-member", approve=True):
    request_id = _query(location)["request"]
    tenant, role = PEOPLE[user]
    with as_tenant(wired_app.app, tenant_id=tenant, user_id=user, role=role):
        resp = await client.post(
            f"/api/v1/connections/requests/{request_id}", json={"approve": approve}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["redirect_to"]


async def _exchange(client, client_id, code, verifier, redirect_uri=REDIRECT):
    return await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        },
    )


async def _sign_in(
    client, wired_app, *, client_id=None, user="user-member", redirect=REDIRECT
):
    client_id = client_id or await _register(client)
    verifier, challenge = _pkce()
    resp = await _authorize(
        client, wired_app, client_id, challenge, redirect_uri=redirect
    )
    assert resp.status_code == 302, resp.text
    back = await _approve(client, wired_app, resp.headers["location"], user=user)
    resp = await _exchange(
        client, client_id, _query(back)["code"], verifier, redirect_uri=redirect
    )
    assert resp.status_code == 200, resp.text
    return client_id, resp.json()


async def _refresh(client, client_id, refresh_token):
    return await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
    )


async def _connections() -> list[Connection]:
    async with session_module.get_session() as session:
        return list((await session.execute(select(Connection))).scalars())


class TestMetadata:

    async def test_names_this_server_and_what_it_supports(self, oauth, wired_app):
        resp = await oauth.get("/.well-known/oauth-authorization-server")

        assert resp.status_code == 200
        meta = resp.json()
        issuer = wired_app.svc._settings.public_origin
        assert meta["issuer"] == issuer
        assert meta["token_endpoint"] == f"{issuer}/oauth/token"
        assert meta["code_challenge_methods_supported"] == ["S256"]
        assert meta["client_id_metadata_document_supported"] is True
        assert meta["authorization_response_iss_parameter_supported"] is True
        assert meta["scopes_supported"] == ["qbrix"]


class TestRegister:

    async def test_a_public_client_registers(self, oauth):
        resp = await oauth.post(
            "/oauth/register",
            json={"client_name": "Claude Code", "redirect_uris": [REDIRECT]},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["client_id"]
        assert body["token_endpoint_auth_method"] == "none"
        assert body["redirect_uris"] == [REDIRECT]

    @pytest.mark.parametrize(
        "body",
        [
            {
                "redirect_uris": [REDIRECT],
                "token_endpoint_auth_method": "client_secret_basic",
            },
            {"redirect_uris": ["http://evil.example/callback"]},
            {"redirect_uris": ["https://ok.example/cb#frag"]},
            {"redirect_uris": ["cursor://oauth/callback"]},
            {"redirect_uris": []},
            {"redirect_uris": [REDIRECT], "client_name": "visit https://spam.example/"},
        ],
    )
    async def test_refuses_what_a_public_client_cant_register(self, oauth, body):
        resp = await oauth.post("/oauth/register", json=body)

        assert resp.status_code == 400
        assert resp.json()["error"] in (
            "invalid_client_metadata",
            "invalid_redirect_uri",
        )

    async def test_a_native_app_may_use_its_own_scheme(self, oauth):
        await _register(
            oauth, application_type="native", redirect_uris=["cursor://oauth/callback"]
        )


class TestSignIn:

    async def test_a_registered_client_signs_in(self, oauth, wired_app):
        client_id = await _register(oauth)
        verifier, challenge = _pkce()

        resp = await _authorize(oauth, wired_app, client_id, challenge)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(
            f"{wired_app.svc._settings.console_origin}/authorize?request="
        )

        with as_tenant(
            wired_app.app, tenant_id=TENANT, user_id="user-member", role="member"
        ):
            shown = await oauth.get(
                f"/api/v1/connections/requests/{_query(location)['request']}"
            )
        assert shown.status_code == 200
        assert shown.json()["client"] == {
            "name": "Claude Code",
            "uri": None,
            "metadata_url": None,
            "registered_by_itself": True,
        }
        assert shown.json()["acts_for"]["email"] == "user-member@example.com"
        assert shown.json()["applies_at_once"] is True

        back = await _approve(oauth, wired_app, location)
        params = _query(back)
        assert back.startswith(REDIRECT)
        assert params["state"] == "st-1"
        assert params["iss"] == wired_app.svc._settings.public_origin

        resp = await _exchange(oauth, client_id, params["code"], verifier)
        assert resp.status_code == 200, resp.text
        assert resp.headers["cache-control"] == "no-store"
        tokens = resp.json()
        assert tokens["access_token"].startswith("qbx_at_")
        assert tokens["refresh_token"].startswith("qbx_rt_")
        assert tokens["token_type"] == "Bearer"
        assert tokens["expires_in"] == 8 * 3600
        assert tokens["scope"] == "qbrix"

        principal = await wired_app.svc.connections.authenticate(
            tokens["access_token"], request_id="req-1"
        )
        [connection] = await _connections()
        assert principal.actor == Actor.connection(
            "user-member",
            connection_id=connection.id,
            client_name="Claude Code",
            request_id="req-1",
        )
        assert principal.tenant_id == TENANT
        assert principal.role == "member"

    async def test_a_client_with_a_metadata_document_signs_in(self, oauth, wired_app):
        verifier, challenge = _pkce()

        resp = await _authorize(
            oauth, wired_app, DOC_URL, challenge, redirect_uri=DOC_REDIRECT
        )
        assert resp.status_code == 302, resp.text
        location = resp.headers["location"]
        with as_tenant(
            wired_app.app, tenant_id=TENANT, user_id="user-member", role="member"
        ):
            shown = await oauth.get(
                f"/api/v1/connections/requests/{_query(location)['request']}"
            )
        assert shown.json()["client"]["metadata_url"] == DOC_URL
        assert shown.json()["client"]["name"] == "Doc Client"

        back = await _approve(oauth, wired_app, location)
        resp = await _exchange(
            oauth, DOC_URL, _query(back)["code"], verifier, redirect_uri=DOC_REDIRECT
        )

        assert resp.status_code == 200, resp.text
        [connection] = await _connections()
        assert connection.client_identity == DOC_URL
        assert connection.client_id == DOC_URL

    async def test_a_loopback_redirect_may_use_any_port(self, oauth, wired_app):
        await _sign_in(oauth, wired_app, redirect="http://127.0.0.1:53111/callback")

    async def test_declining_sends_the_client_access_denied(self, oauth, wired_app):
        client_id = await _register(oauth)
        _, challenge = _pkce()
        resp = await _authorize(oauth, wired_app, client_id, challenge)

        back = await _approve(oauth, wired_app, resp.headers["location"], approve=False)

        params = _query(back)
        assert params["error"] == "access_denied"
        assert params["state"] == "st-1"
        assert params["iss"] == wired_app.svc._settings.public_origin
        assert "code" not in params

    async def test_a_request_is_answered_once(self, oauth, wired_app):
        client_id = await _register(oauth)
        _, challenge = _pkce()
        location = (await _authorize(oauth, wired_app, client_id, challenge)).headers[
            "location"
        ]
        await _approve(oauth, wired_app, location)

        request_id = _query(location)["request"]
        with as_tenant(
            wired_app.app, tenant_id=TENANT, user_id="user-member", role="member"
        ):
            resp = await oauth.post(
                f"/api/v1/connections/requests/{request_id}", json={"approve": True}
            )
        assert resp.status_code == 404
        assert resp.json()["code"] == "OAUTH_REQUEST_NOT_FOUND"

    async def test_a_viewer_can_sign_a_client_in(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app, user="user-viewer")

        principal = await wired_app.svc.connections.authenticate(tokens["access_token"])
        assert principal.role == "viewer"


class TestAuthorizeRefusals:

    @pytest.mark.parametrize(
        "overrides, error",
        [
            ({"code_challenge": None}, "invalid_request"),
            ({"code_challenge_method": "plain"}, "invalid_request"),
            ({"code_challenge_method": None}, "invalid_request"),
            ({"resource": "https://elsewhere.example/mcp"}, "invalid_target"),
            ({"resource": None}, "invalid_target"),
            ({"scope": "qbrix admin"}, "invalid_scope"),
            ({"response_type": "token"}, "unsupported_response_type"),
        ],
    )
    async def test_errors_go_back_to_the_client_with_iss(
        self, oauth, wired_app, overrides, error
    ):
        client_id = await _register(oauth)
        _, challenge = _pkce()

        resp = await _authorize(oauth, wired_app, client_id, challenge, **overrides)

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(REDIRECT)
        params = _query(location)
        assert params["error"] == error
        assert params["state"] == "st-1"
        assert params["iss"] == wired_app.svc._settings.public_origin

    async def test_an_unregistered_redirect_uri_is_never_redirected_to(
        self, oauth, wired_app
    ):
        client_id = await _register(oauth)
        _, challenge = _pkce()

        resp = await _authorize(
            oauth,
            wired_app,
            client_id,
            challenge,
            redirect_uri="https://evil.example/cb",
        )

        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_an_unknown_client_is_refused(self, oauth, wired_app):
        _, challenge = _pkce()

        resp = await _authorize(oauth, wired_app, "no-such-client", challenge)

        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_client"


class TestCode:

    async def _code(self, oauth, wired_app):
        client_id = await _register(oauth)
        verifier, challenge = _pkce()
        resp = await _authorize(oauth, wired_app, client_id, challenge)
        back = await _approve(oauth, wired_app, resp.headers["location"])
        return client_id, _query(back)["code"], verifier

    async def test_a_code_works_once(self, oauth, wired_app):
        client_id, code, verifier = await self._code(oauth, wired_app)
        assert (await _exchange(oauth, client_id, code, verifier)).status_code == 200

        resp = await _exchange(oauth, client_id, code, verifier)

        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"

    async def test_a_code_lives_60_seconds(self, oauth, wired_app):
        client_id, code, verifier = await self._code(oauth, wired_app)
        [key] = await wired_app.fake_redis.keys("qbrix:oauth:code:*")
        assert 0 < await wired_app.fake_redis.ttl(key) <= 60

        await wired_app.fake_redis.delete(key)
        resp = await _exchange(oauth, client_id, code, verifier)

        assert resp.json()["error"] == "invalid_grant"

    @pytest.mark.parametrize(
        "field, value",
        [
            ("code_verifier", "x" * 64),
            ("redirect_uri", "http://127.0.0.1/other"),
            ("client_id", "another-client"),
        ],
    )
    async def test_a_code_is_bound_to_its_request(self, oauth, wired_app, field, value):
        client_id, code, verifier = await self._code(oauth, wired_app)
        form = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT,
            field: value,
        }

        resp = await oauth.post("/oauth/token", data=form)

        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"


class TestConnection:

    async def test_signing_in_again_renews_the_connection(self, oauth, wired_app):
        _, first = await _sign_in(oauth, wired_app)
        _, second = await _sign_in(oauth, wired_app)

        connections = await _connections()
        assert len(connections) == 1
        with pytest.raises(ConnectionTokenInvalidError):
            await wired_app.svc.connections.authenticate(first["access_token"])
        await wired_app.svc.connections.authenticate(second["access_token"])

    async def test_two_clients_are_two_connections(self, oauth, wired_app):
        await _sign_in(oauth, wired_app)
        await _sign_in(
            oauth, wired_app, client_id=await _register(oauth, client_name="Cursor")
        )

        assert len(await _connections()) == 2


class TestRefresh:

    async def test_a_refresh_rotates_both_tokens(self, oauth, wired_app):
        client_id, first = await _sign_in(oauth, wired_app)

        resp = await _refresh(oauth, client_id, first["refresh_token"])

        assert resp.status_code == 200, resp.text
        second = resp.json()
        assert second["access_token"] != first["access_token"]
        assert second["refresh_token"] != first["refresh_token"]
        with pytest.raises(ConnectionTokenInvalidError):
            await wired_app.svc.connections.authenticate(first["access_token"])
        await wired_app.svc.connections.authenticate(second["access_token"])

    async def test_a_used_refresh_token_revokes_the_connection(self, oauth, wired_app):
        client_id, first = await _sign_in(oauth, wired_app)
        second = (await _refresh(oauth, client_id, first["refresh_token"])).json()

        resp = await _refresh(oauth, client_id, first["refresh_token"])

        assert resp.json()["error"] == "invalid_grant"
        [connection] = await _connections()
        assert connection.revoked_at is not None
        with pytest.raises(ConnectionTokenInvalidError):
            await wired_app.svc.connections.authenticate(second["access_token"])
        resp = await _refresh(oauth, client_id, second["refresh_token"])
        assert resp.json()["error"] == "invalid_grant"

    async def test_a_connection_unused_for_90_days_cant_refresh(self, oauth, wired_app):
        client_id, tokens = await _sign_in(oauth, wired_app)
        long_ago = datetime.now(timezone.utc) - timedelta(days=91)
        async with session_module.get_session() as session:
            await session.execute(
                update(Connection).values(created_at=long_ago, last_used_at=long_ago)
            )

        resp = await _refresh(oauth, client_id, tokens["refresh_token"])

        assert resp.json()["error"] == "invalid_grant"
        assert "90 days" in resp.json()["error_description"]

    async def test_a_refresh_token_belongs_to_its_client(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app)

        resp = await _refresh(oauth, "another-client", tokens["refresh_token"])

        assert resp.json()["error"] == "invalid_grant"


class TestAuthenticate:

    async def test_a_refresh_token_isnt_an_access_token(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app)

        with pytest.raises(ConnectionTokenInvalidError):
            await wired_app.svc.connections.authenticate(tokens["refresh_token"])

    async def test_an_expired_token_is_refused(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app)
        async with session_module.get_session() as session:
            await session.execute(
                update(ConnectionToken).values(
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
                )
            )

        with pytest.raises(ConnectionTokenInvalidError):
            await wired_app.svc.connections.authenticate(tokens["access_token"])

    async def test_a_token_is_only_for_this_servers_mcp(
        self, oauth, wired_app, monkeypatch
    ):
        _, tokens = await _sign_in(oauth, wired_app)
        monkeypatch.setattr(
            wired_app.svc._settings, "public_url", "https://another.example"
        )

        with pytest.raises(ConnectionTokenInvalidError):
            await wired_app.svc.connections.authenticate(tokens["access_token"])

    async def test_an_inactive_persons_token_is_refused(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app)
        async with session_module.get_session() as session:
            await session.execute(
                update(User).where(User.id == "user-member").values(is_active=False)
            )

        with pytest.raises(ConnectionTokenInvalidError):
            await wired_app.svc.connections.authenticate(tokens["access_token"])

    async def test_the_role_is_the_persons_role_now(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app)
        connections = wired_app.svc.connections
        assert (await connections.authenticate(tokens["access_token"])).role == "member"

        async with session_module.get_session() as session:
            await session.execute(
                update(User).where(User.id == "user-member").values(role="viewer")
            )

        assert (await connections.authenticate(tokens["access_token"])).role == "viewer"

    async def test_use_is_recorded_at_most_once_a_minute(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app)
        connections = wired_app.svc.connections

        await connections.authenticate(tokens["access_token"])
        [connection] = await _connections()
        first = connection.last_used_at
        assert first is not None
        await connections.authenticate(tokens["access_token"])

        [connection] = await _connections()
        assert connection.last_used_at == first

    async def test_each_connection_has_its_own_limit(
        self, oauth, wired_app, monkeypatch
    ):
        monkeypatch.setattr(wired_app.svc._settings, "mcp_calls_per_minute", 2)
        _, first = await _sign_in(oauth, wired_app)
        _, second = await _sign_in(oauth, wired_app, user="user-admin")
        connections = wired_app.svc.connections

        await connections.authenticate(first["access_token"])
        await connections.authenticate(first["access_token"])
        with pytest.raises(ConnectionRateLimitedError) as refused:
            await connections.authenticate(first["access_token"])

        assert 0 < refused.value.retry_after <= 60
        await connections.authenticate(second["access_token"])


class TestRevoke:

    async def test_a_client_revokes_its_connection(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app)

        resp = await oauth.post(
            "/oauth/revoke", data={"token": tokens["refresh_token"]}
        )

        assert resp.status_code == 200
        with pytest.raises(ConnectionTokenInvalidError):
            await wired_app.svc.connections.authenticate(tokens["access_token"])

    async def test_an_unknown_token_is_not_an_error(self, oauth):
        resp = await oauth.post("/oauth/revoke", data={"token": "qbx_at_nothing"})

        assert resp.status_code == 200

    async def test_revoking_one_connection_leaves_the_others(self, oauth, wired_app):
        _, kept = await _sign_in(oauth, wired_app)
        _, gone = await _sign_in(
            oauth, wired_app, client_id=await _register(oauth, client_name="Cursor")
        )

        await oauth.post("/oauth/revoke", data={"token": gone["access_token"]})

        await wired_app.svc.connections.authenticate(kept["access_token"])


class TestConnectionsApi:

    async def _list(self, oauth, wired_app, user):
        tenant, role = PEOPLE[user]
        with as_tenant(wired_app.app, tenant_id=tenant, user_id=user, role=role):
            resp = await oauth.get("/api/v1/connections")
        assert resp.status_code == 200, resp.text
        return resp.json()["connections"]

    async def _delete(self, oauth, wired_app, user, connection_id):
        tenant, role = PEOPLE[user]
        with as_tenant(wired_app.app, tenant_id=tenant, user_id=user, role=role):
            return await oauth.delete(f"/api/v1/connections/{connection_id}")

    async def _three(self, oauth, wired_app):
        for user in ("user-member", "user-viewer", "user-b"):
            await _sign_in(oauth, wired_app, user=user)

    async def test_people_see_their_own_and_admins_their_workspace(
        self, oauth, wired_app
    ):
        await self._three(oauth, wired_app)

        mine = await self._list(oauth, wired_app, "user-member")
        assert [c["user"]["id"] for c in mine] == ["user-member"]
        assert mine[0]["client"]["name"] == "Claude Code"
        assert [
            c["user"]["id"] for c in await self._list(oauth, wired_app, "user-viewer")
        ] == ["user-viewer"]
        everyone = await self._list(oauth, wired_app, "user-admin")
        assert {c["user"]["id"] for c in everyone} == {"user-member", "user-viewer"}

    async def test_people_revoke_their_own_and_admins_any_in_their_workspace(
        self, oauth, wired_app
    ):
        await self._three(oauth, wired_app)
        [viewers] = await self._list(oauth, wired_app, "user-viewer")
        [members] = await self._list(oauth, wired_app, "user-member")

        refused = await self._delete(oauth, wired_app, "user-member", viewers["id"])
        assert refused.status_code == 404
        assert refused.json()["code"] == "CONNECTION_NOT_FOUND"
        other_workspace = await self._delete(oauth, wired_app, "user-b", members["id"])
        assert other_workspace.status_code == 404

        assert (
            await self._delete(oauth, wired_app, "user-member", members["id"])
        ).status_code == 204
        assert (
            await self._delete(oauth, wired_app, "user-admin", viewers["id"])
        ).status_code == 204
        assert await self._list(oauth, wired_app, "user-admin") == []

    @pytest.mark.parametrize(
        "method, path",
        [
            ("GET", "/api/v1/connections"),
            ("DELETE", "/api/v1/connections/any"),
            ("GET", "/api/v1/connections/requests/any"),
            ("POST", "/api/v1/connections/requests/any"),
        ],
    )
    async def test_an_api_key_is_refused(self, oauth, wired_app, method, path):
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-member", api_key_id="key-1")
        try:
            with as_tenant(wired_app.app, tenant_id=TENANT, user_id="user-member"):
                resp = await oauth.request(
                    method, path, json={"approve": True} if method == "POST" else None
                )
        finally:
            overrides.pop(get_actor, None)

        assert resp.status_code == 403


class TestStoredState:

    async def test_only_hashes_are_stored(self, oauth, wired_app):
        _, tokens = await _sign_in(oauth, wired_app)

        async with session_module.get_session() as session:
            stored = [
                t.token_hash
                for t in (await session.execute(select(ConnectionToken))).scalars()
            ]
        assert tokens["access_token"] not in stored
        assert hashlib.sha256(tokens["access_token"].encode()).hexdigest() in stored

    async def test_a_pending_request_waits_10_minutes(self, oauth, wired_app):
        client_id = await _register(oauth)
        _, challenge = _pkce()
        await _authorize(oauth, wired_app, client_id, challenge)

        [key] = await wired_app.fake_redis.keys("qbrix:oauth:request:*")
        assert 540 < await wired_app.fake_redis.ttl(key) <= 600
        assert json.loads(await wired_app.fake_redis.get(key))["state"] == "st-1"
