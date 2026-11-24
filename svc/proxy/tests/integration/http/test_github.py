"""integration tests for connecting a workspace's own github app, a qbrix
next surface, against a fake github.

invariants verified:
  an admin gets a manifest naming this install's addresses and asking only
  to read; github's code becomes the workspace's app, whose private key and
  webhook secret are stored only sealed and never read back; the admin goes
  on to install it, and the installation is recorded only once github says
  it is the app's. a state that is forged, expired, for another step or for
  an app since replaced is refused at both callbacks. the read names who set
  it up and the repositories github lets it see. reachability is false up
  front for an address github can't reach, false a minute after installing
  with no event, and true once a signed event arrives; an unsigned one is
  refused. installation events keep the installation current. disconnecting
  removes the installation on github first, keeps everything when github is
  down, and says where to delete the app. two workspaces never see each
  other's app. members and viewers read; only an admin connects or
  disconnects, never an api key or a connection's token. none of it is a
  change.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from sqlalchemy import func
from sqlalchemy import select

import proxysvc.config
from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import GitHubApp
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User
from qbrixstore.postgres.session import get_session

from proxysvc.core.actor import Actor
from proxysvc.mod.github.client import GitHubClient
from proxysvc.mod.github.service import GitHubService
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
OTHER_TENANT = "other-tenant"
ADA = "user-ada"
BEN = "user-ben"
ORIGIN = "https://qbrix.example.com"
CONSOLE = "https://console.example.com"
SETTINGS_PAGE = f"{CONSOLE}/next/settings/workspace/github"
START = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)


def _pem() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public


KEYS = [_pem(), _pem()]


class _GitHub:
    """github's api as the flow uses it: each manifest code becomes a new app
    with its own key, and app calls must carry a jwt that key signed."""

    def __init__(self):
        self.apps: dict[int, dict] = {}
        self.codes: dict[str, int] = {}
        self.installations: dict[int, int] = {}
        self.repositories = ["acme/shop", "acme/site"]
        self.deleted: list[int] = []
        self.requests: list[httpx.Request] = []
        self.down = False
        self._ids = itertools.count(100)

    def code(self, owner="ada", owner_type="User") -> str:
        app_id = next(self._ids)
        private, public = KEYS[len(self.apps) % len(KEYS)]
        self.apps[app_id] = {
            "id": app_id,
            "slug": f"qbrix-acme-{app_id}",
            "client_id": f"Iv1.{app_id}",
            "owner": {"login": owner, "type": owner_type},
            "pem": private,
            "public": public,
            "webhook_secret": f"whsec-{app_id}",
        }
        code = f"code-{app_id}"
        self.codes[code] = app_id
        return code

    def install(self, app_id: int) -> int:
        installation_id = 5000 + app_id
        self.installations[installation_id] = app_id
        return installation_id

    def _app(self, request: httpx.Request) -> int | None:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        claims = jwt.get_unverified_claims(token)
        app = self.apps.get(int(claims["iss"]))
        if app is None:
            return None
        claims = jwt.decode(
            token, app["public"], algorithms=["RS256"], options={"verify_exp": False}
        )
        assert claims["exp"] - claims["iat"] <= 600
        return app["id"]

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.down:
                raise httpx.ConnectError("github is down", request=request)
            path = request.url.path
            if path.startswith("/app-manifests/"):
                app_id = self.codes.pop(path.split("/")[2], None)
                if app_id is None:
                    return httpx.Response(404)
                app = self.apps[app_id]
                return httpx.Response(
                    201, json={k: v for k, v in app.items() if k != "public"}
                )
            if path == "/installation/repositories":
                page = int(request.url.params["page"])
                names = self.repositories if page == 1 else []
                return httpx.Response(
                    200,
                    json={
                        "total_count": len(self.repositories),
                        "repositories": [{"full_name": n} for n in names],
                    },
                )
            app_id = self._app(request)
            if app_id is None:
                return httpx.Response(401)
            installation_id = int(path.split("/")[3])
            if self.installations.get(installation_id) != app_id:
                return httpx.Response(404)
            if path.endswith("/access_tokens"):
                expires = START + timedelta(hours=1)
                return httpx.Response(
                    201,
                    json={"token": "ghs_x", "expires_at": expires.isoformat()},
                )
            if request.method == "DELETE":
                del self.installations[installation_id]
                self.deleted.append(installation_id)
                return httpx.Response(204)
            return httpx.Response(200, json={"id": installation_id})

        return httpx.MockTransport(handle)


class _Clock:
    def __init__(self):
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def _service(wired_app, github: _GitHub, clock: _Clock, *, origin=ORIGIN):
    settings = wired_app.svc._settings.model_copy(
        update={"public_url": origin, "console_url": CONSOLE}
    )
    return GitHubService(
        settings=settings,
        client=GitHubClient(transport=github.transport()),
        clock=clock,
    )


@pytest_asyncio.fixture
async def github(wired_app, next_enabled) -> _GitHub:
    return _GitHub()


@pytest_asyncio.fixture
async def clock(wired_app, github) -> _Clock:
    clock = _Clock()
    wired_app.svc._github_service = _service(wired_app, github, clock)
    return clock


@pytest_asyncio.fixture
async def api(wired_app, client, clock):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    async with get_session() as session:
        session.add(Tenant(id=TENANT, name="Acme", slug="acme"))
        session.add(Tenant(id=OTHER_TENANT, name="Other", slug="other"))
        for user_id, name, tenant in (
            (ADA, "Ada", TENANT),
            (BEN, "Ben", OTHER_TENANT),
        ):
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant,
                    email=f"{user_id}@example.com",
                    password_hash="x",
                    name=name,
                )
            )
    with as_tenant(app, tenant_id=TENANT, user_id=ADA, role="admin"):
        yield client
    app.router.routes[:] = routes


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


async def _read(api) -> dict:
    resp = await api.get("/api/v1/github")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _connect(api, **body) -> dict:
    resp = await api.post("/api/v1/github/connect", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _created(api, github: _GitHub, state: str, **code) -> httpx.Response:
    return await api.get(
        "/api/v1/github/created", params={"code": github.code(**code), "state": state}
    )


async def _connected(api, github: _GitHub) -> int:
    """run the whole flow and return the installation's id."""
    state = _query((await _connect(api))["form_action"])["state"]
    install_state = _query((await _created(api, github, state)).headers["location"])[
        "state"
    ]
    app_id = max(github.apps)
    installation_id = github.install(app_id)
    resp = await api.get(
        "/api/v1/github/installed",
        params={
            "installation_id": installation_id,
            "setup_action": "install",
            "state": install_state,
        },
    )
    assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=installed"
    return installation_id


async def _stored() -> GitHubApp:
    async with get_session() as session:
        return (await session.execute(select(GitHubApp))).scalar_one()


async def _event(api, token: str, name: str, payload: dict, secret: str):
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return await api.post(
        f"/api/v1/github/events/{token}",
        content=body,
        headers={
            "x-github-event": name,
            "x-hub-signature-256": f"sha256={signature}",
            "content-type": "application/json",
        },
    )


class TestConnect:
    async def test_the_manifest_names_this_install_and_only_reads(self, api):
        made = await _connect(api)

        assert made["form_action"].startswith("https://github.com/settings/apps/new?")
        manifest = made["manifest"]
        token = manifest["hook_attributes"]["url"].rsplit("/", 1)[1]
        assert manifest["name"] == "qbrix-acme"
        assert manifest["hook_attributes"] == {
            "url": f"{ORIGIN}/api/v1/github/events/{token}",
            "active": True,
        }
        assert manifest["redirect_url"] == f"{ORIGIN}/api/v1/github/created"
        assert manifest["setup_url"] == f"{ORIGIN}/api/v1/github/installed"
        assert manifest["public"] is False
        assert manifest["default_permissions"] == {
            "pull_requests": "read",
            "contents": "read",
            "metadata": "read",
        }
        assert manifest["default_events"] == ["pull_request", "push"]

    async def test_an_organisation_gets_its_own_form(self, api):
        made = await _connect(api, organisation="acme-inc")

        assert made["form_action"].startswith(
            "https://github.com/organizations/acme-inc/settings/apps/new?state="
        )

    async def test_an_organisation_name_github_would_refuse_is_refused(self, api):
        resp = await api.post(
            "/api/v1/github/connect", json={"organisation": "../settings"}
        )

        assert resp.status_code == 422

    async def test_connecting_stores_nothing_until_github_answers(self, api):
        await _connect(api)

        assert (await _read(api))["connected"] is False
        async with get_session() as session:
            count = await session.execute(select(func.count()).select_from(GitHubApp))
            assert count.scalar_one() == 0

    async def test_an_installed_app_must_be_disconnected_first(self, api, github):
        await _connected(api, github)

        resp = await api.post("/api/v1/github/connect", json={})

        assert resp.status_code == 409
        assert resp.json()["code"] == "GITHUB_ALREADY_CONNECTED"


class TestCreated:
    async def test_stores_the_app_sealed_and_sends_the_admin_to_install(
        self, api, github
    ):
        state = _query((await _connect(api))["form_action"])["state"]

        resp = await _created(api, github, state)

        assert resp.status_code == 303
        app = github.apps[max(github.apps)]
        location = resp.headers["location"]
        assert location.startswith(
            f"https://github.com/apps/{app['slug']}/installations/new?state="
        )
        stored = await _stored()
        assert stored.app_id == app["id"]
        assert stored.owner == "ada"
        assert stored.created_by == ADA
        for secret, sealed in (
            (app["pem"], stored.private_key_ciphertext),
            (app["webhook_secret"], stored.webhook_secret_ciphertext),
        ):
            assert sealed.startswith("v1.")
            assert secret not in sealed

    async def test_a_forged_state_is_refused(self, api, github):
        resp = await _created(api, github, "forged")

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=state"
        async with get_session() as session:
            count = await session.execute(select(func.count()).select_from(GitHubApp))
            assert count.scalar_one() == 0

    async def test_an_expired_state_is_refused(self, api, github, clock):
        state = _query((await _connect(api))["form_action"])["state"]
        clock.now += timedelta(minutes=16)

        resp = await _created(api, github, state)

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=state"

    async def test_the_install_state_is_refused_here(self, api, github):
        state = _query((await _connect(api))["form_action"])["state"]
        install_state = _query(
            (await _created(api, github, state)).headers["location"]
        )["state"]

        resp = await _created(api, github, install_state)

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=state"

    async def test_github_down_says_so(self, api, github):
        state = _query((await _connect(api))["form_action"])["state"]
        github.down = True

        resp = await _created(api, github, state)

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=unavailable"

    async def test_a_second_app_replaces_one_never_installed(self, api, github):
        for _ in range(2):
            state = _query((await _connect(api))["form_action"])["state"]
            await _created(api, github, state)

        assert (await _stored()).app_id == max(github.apps)


class TestInstalled:
    async def test_records_the_installation_github_confirms(self, api, github):
        installation_id = await _connected(api, github)

        stored = await _stored()
        assert stored.installation_id == installation_id
        assert stored.installed_at is not None
        assert (await _read(api))["connected"] is True

    async def test_another_apps_installation_is_refused(self, api, github):
        state = _query((await _connect(api))["form_action"])["state"]
        install_state = _query(
            (await _created(api, github, state)).headers["location"]
        )["state"]
        github.code()
        stranger = github.install(max(github.apps))

        resp = await api.get(
            "/api/v1/github/installed",
            params={"installation_id": stranger, "state": install_state},
        )

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=state"
        assert (await _stored()).installation_id is None

    async def test_a_state_for_a_replaced_app_is_refused(self, api, github):
        state = _query((await _connect(api))["form_action"])["state"]
        stale = _query((await _created(api, github, state)).headers["location"])[
            "state"
        ]
        first = max(github.apps)
        state = _query((await _connect(api))["form_action"])["state"]
        await _created(api, github, state)

        resp = await api.get(
            "/api/v1/github/installed",
            params={"installation_id": github.install(first), "state": stale},
        )

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=state"

    async def test_a_forged_state_is_refused(self, api, github):
        state = _query((await _connect(api))["form_action"])["state"]
        await _created(api, github, state)

        resp = await api.get(
            "/api/v1/github/installed",
            params={"installation_id": github.install(max(github.apps)), "state": "x"},
        )

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=state"

    async def test_a_state_from_another_workspace_is_refused(
        self, wired_app, api, github
    ):
        with as_tenant(wired_app.app, tenant_id=OTHER_TENANT, user_id=BEN):
            other = _query((await _connect(api))["form_action"])["state"]
            other_install = _query(
                (await _created(api, github, other)).headers["location"]
            )["state"]
        state = _query((await _connect(api))["form_action"])["state"]
        await _created(api, github, state)
        ours = github.install(max(github.apps))

        resp = await api.get(
            "/api/v1/github/installed",
            params={"installation_id": ours, "state": other_install},
        )

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=state"

    async def test_a_request_to_an_organisation_owner_says_so(self, api):
        resp = await api.get(
            "/api/v1/github/installed", params={"setup_action": "request"}
        )

        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=requested"

    async def test_an_admin_can_finish_an_installation_left_half_done(
        self, api, github
    ):
        state = _query((await _connect(api))["form_action"])["state"]
        await _created(api, github, state)

        read = await _read(api)
        resp = await api.get(
            "/api/v1/github/installed",
            params={
                "installation_id": github.install(max(github.apps)),
                "state": _query(read["install_url"])["state"],
            },
        )

        assert read["connected"] is False
        assert resp.headers["location"] == f"{SETTINGS_PAGE}?github=installed"


class TestRead:
    async def test_names_who_set_it_up_and_the_repositories(self, api, github):
        await _connected(api, github)

        read = await _read(api)

        assert read["connected"] is True
        assert read["owner"] == "ada"
        assert read["set_up_by"] == {"id": ADA, "name": "Ada"}
        assert read["at"] == START.isoformat()
        assert read["repositories"] == [
            {"full_name": "acme/shop", "mentions": 0, "last_mention": None},
            {"full_name": "acme/site", "mentions": 0, "last_mention": None},
        ]
        assert read["manage_url"].startswith(
            "https://github.com/settings/installations/"
        )
        assert read["install_url"] is None

    async def test_never_carries_a_secret(self, api, github):
        await _connected(api, github)
        app = github.apps[max(github.apps)]

        text = json.dumps(await _read(api))

        assert app["pem"] not in text
        assert app["webhook_secret"] not in text

    async def test_repositories_are_cached_for_a_minute(self, api, github):
        await _connected(api, github)
        await _read(api)
        github.repositories = ["acme/new"]

        cached = await _read(api)

        assert [r["full_name"] for r in cached["repositories"]] == [
            "acme/shop",
            "acme/site",
        ]

    async def test_github_down_leaves_the_repositories_unknown(self, api, github):
        await _connected(api, github)
        github.down = True

        read = await _read(api)

        assert read["connected"] is True
        assert read["repositories"] is None

    async def test_nothing_connected(self, api):
        assert await _read(api) == {
            "connected": False,
            "owner": None,
            "set_up_by": None,
            "at": None,
            "repositories": [],
            "reachable": None,
            "reach_note": None,
            "manage_url": None,
            "install_url": None,
        }


class TestReachable:
    @pytest.mark.parametrize(
        "origin", ["http://localhost:8080", "https://qbrix.internal:8000"]
    )
    async def test_an_address_github_cant_reach_says_so_up_front(
        self, wired_app, api, github, clock, origin
    ):
        wired_app.svc._github_service = _service(
            wired_app, github, clock, origin=origin
        )

        read = await _read(api)

        assert read["reachable"] is False
        assert read["reach_note"].startswith("GitHub can't reach")

    async def test_unknown_for_a_minute_then_unreachable(self, api, github, clock):
        await _connected(api, github)

        assert (await _read(api))["reachable"] is None
        clock.now += timedelta(seconds=60)
        read = await _read(api)

        assert read["reachable"] is False
        assert "hasn't reached qbrix.example.com" in read["reach_note"]

    async def test_a_signed_event_shows_github_reaches_it(self, api, github, clock):
        await _connected(api, github)
        clock.now += timedelta(minutes=5)
        stored = await _stored()
        secret = github.apps[stored.app_id]["webhook_secret"]

        resp = await _event(api, stored.events_token, "ping", {"zen": "hi"}, secret)

        assert resp.status_code == 204
        read = await _read(api)
        assert read["reachable"] is True
        assert read["reach_note"] is None

    async def test_an_unsigned_event_is_refused(self, api, github):
        await _connected(api, github)
        stored = await _stored()

        resp = await _event(api, stored.events_token, "ping", {}, "wrong")

        assert resp.status_code == 401
        assert (await _stored()).last_event_at is None

    async def test_an_unknown_address_is_refused(self, api):
        resp = await _event(api, "nobody", "ping", {}, "x")

        assert resp.status_code == 404


class TestInstallationEvents:
    async def test_an_install_done_on_github_is_recorded(self, api, github):
        state = _query((await _connect(api))["form_action"])["state"]
        await _created(api, github, state)
        stored = await _stored()
        installation_id = github.install(stored.app_id)

        await _event(
            api,
            stored.events_token,
            "installation",
            {"action": "created", "installation": {"id": installation_id}},
            github.apps[stored.app_id]["webhook_secret"],
        )

        read = await _read(api)
        assert read["connected"] is True
        assert read["reachable"] is True

    async def test_uninstalling_on_github_disconnects(self, api, github):
        installation_id = await _connected(api, github)
        stored = await _stored()

        await _event(
            api,
            stored.events_token,
            "installation",
            {"action": "deleted", "installation": {"id": installation_id}},
            github.apps[stored.app_id]["webhook_secret"],
        )

        assert (await _read(api))["connected"] is False


class TestDisconnect:
    async def test_removes_the_installation_on_github_then_here(self, api, github):
        installation_id = await _connected(api, github)
        slug = (await _stored()).slug

        resp = await api.delete("/api/v1/github")

        assert resp.status_code == 200
        assert resp.json() == {
            "app_settings_url": f"https://github.com/settings/apps/{slug}"
        }
        assert github.deleted == [installation_id]
        assert (await _read(api))["connected"] is False
        async with get_session() as session:
            count = await session.execute(select(func.count()).select_from(GitHubApp))
            assert count.scalar_one() == 0

    async def test_an_organisations_app_is_deleted_there(self, api, github):
        state = _query((await _connect(api, organisation="acme-inc"))["form_action"])[
            "state"
        ]
        await _created(api, github, state, owner="acme-inc", owner_type="Organization")

        resp = await api.delete("/api/v1/github")

        assert resp.json()["app_settings_url"].startswith(
            "https://github.com/organizations/acme-inc/settings/apps/"
        )

    async def test_github_down_keeps_everything(self, api, github):
        await _connected(api, github)
        github.down = True

        resp = await api.delete("/api/v1/github")

        assert resp.status_code == 503
        assert resp.json()["code"] == "GITHUB_UNAVAILABLE"
        assert (await _stored()).installation_id is not None

    async def test_an_installation_already_gone_still_disconnects(self, api, github):
        installation_id = await _connected(api, github)
        del github.installations[installation_id]

        assert (await api.delete("/api/v1/github")).status_code == 200

    async def test_nothing_to_disconnect(self, api):
        resp = await api.delete("/api/v1/github")

        assert resp.status_code == 404
        assert resp.json()["code"] == "GITHUB_NOT_CONNECTED"


class TestWorkspaces:
    async def test_each_workspace_sees_only_its_own_app(self, wired_app, api, github):
        await _connected(api, github)
        with as_tenant(wired_app.app, tenant_id=OTHER_TENANT, user_id=BEN):
            other = await _read(api)
            made = await _connect(api)

        assert other["connected"] is False
        assert other["owner"] is None
        assert made["manifest"]["name"] == "qbrix-other"
        assert (await _read(api))["connected"] is True


class TestRoles:
    @pytest.mark.parametrize("role", ["member", "viewer"])
    async def test_read_but_not_connect_or_disconnect(
        self, wired_app, api, github, role
    ):
        state = _query((await _connect(api))["form_action"])["state"]
        await _created(api, github, state)
        with as_tenant(wired_app.app, tenant_id=TENANT, user_id=ADA, role=role):
            read = await _read(api)
            writes = [
                await api.post("/api/v1/github/connect", json={}),
                await api.delete("/api/v1/github"),
            ]

        assert read["owner"] == "ada"
        assert read["install_url"] is None
        assert [w.status_code for w in writes] == [403, 403]

    async def test_an_api_key_is_refused(self, wired_app, api):
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member(ADA, api_key_id="key-1")
        try:
            writes = [
                await api.post("/api/v1/github/connect", json={}),
                await api.delete("/api/v1/github"),
            ]
        finally:
            del overrides[get_actor]

        assert [w.status_code for w in writes] == [403, 403]

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
                await api.post("/api/v1/github/connect", json={}, headers=headers),
                await api.delete("/api/v1/github", headers=headers),
            ]
        finally:
            app.dependency_overrides.update(saved)

        assert [w.status_code for w in writes] == [401, 401]

    async def test_the_callbacks_and_events_need_no_session(
        self, wired_app, api, github, monkeypatch
    ):
        app = wired_app.app
        saved = dict(app.dependency_overrides)
        app.dependency_overrides.clear()
        monkeypatch.setattr(proxysvc.config.settings, "runenv", "prod")
        try:
            created = await api.get("/api/v1/github/created", params={"state": "x"})
            installed = await api.get(
                "/api/v1/github/installed", params={"installation_id": 1}
            )
            event = await _event(api, "nobody", "ping", {}, "x")
            read = await api.get("/api/v1/github")
        finally:
            app.dependency_overrides.update(saved)

        assert created.status_code == 303
        assert installed.status_code == 303
        assert event.status_code == 404
        assert read.status_code == 401


class TestNotAChange:
    async def test_connecting_and_disconnecting_record_no_change(self, api, github):
        await _connected(api, github)
        await api.delete("/api/v1/github")

        async with get_session() as session:
            count = await session.execute(select(func.count()).select_from(Change))
            assert count.scalar_one() == 0
