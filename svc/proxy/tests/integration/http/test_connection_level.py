from __future__ import annotations

import pytest
from sqlalchemy import select

from qbrixstore.postgres import session as session_module
from qbrixstore.postgres.models import ConnectionLevel

from proxysvc.core import autonomy
from proxysvc.core.actor import Actor
from proxysvc.core.error import ConnectionLevelsForbiddenError
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant
from svc.proxy.tests.integration.http.test_oauth import PEOPLE
from svc.proxy.tests.integration.http.test_oauth import _sign_in
from svc.proxy.tests.integration.http.test_oauth import oauth  # noqa: F401

TENANT_A = PEOPLE["user-member"][0]


async def _request(client, wired_app, user, method, path, body=None):
    tenant, role = PEOPLE[user]
    with as_tenant(wired_app.app, tenant_id=tenant, user_id=user, role=role):
        return await client.request(method, path, json=body)


async def _connection(client, wired_app, user="user-member") -> str:
    await _sign_in(client, wired_app, user=user)
    resp = await _request(client, wired_app, user, "GET", "/api/v1/connections")
    [connection] = [c for c in resp.json()["connections"] if c["user"]["id"] == user]
    return connection["id"]


def _levels(resp) -> dict[str, str]:
    assert resp.status_code == 200, resp.text
    return {entry["kind"]: entry["level"] for entry in resp.json()["levels"]}


async def _stored() -> dict[str, str]:
    async with session_module.get_session() as session:
        rows = (await session.execute(select(ConnectionLevel))).scalars()
        return {row.kind: row.level for row in rows}


class TestReading:

    async def test_a_new_connection_reads_the_defaults_and_no_reads(
        self, oauth, wired_app
    ):
        connection = await _connection(oauth, wired_app)

        resp = await _request(
            oauth,
            wired_app,
            "user-member",
            "GET",
            f"/api/v1/connections/{connection}/levels",
        )

        assert _levels(resp) == autonomy.DEFAULTS
        assert all(e["level"] == e["default"] for e in resp.json()["levels"])
        assert await _stored() == {}

    async def test_an_admin_reads_anyones_and_a_member_only_their_own(
        self, oauth, wired_app
    ):
        viewers = await _connection(oauth, wired_app, user="user-viewer")
        path = f"/api/v1/connections/{viewers}/levels"

        assert (
            await _request(oauth, wired_app, "user-admin", "GET", path)
        ).status_code == 200
        refused = await _request(oauth, wired_app, "user-member", "GET", path)
        assert refused.status_code == 404
        assert refused.json()["code"] == "CONNECTION_NOT_FOUND"
        assert (
            await _request(oauth, wired_app, "user-b", "GET", path)
        ).status_code == 404


class TestSetting:

    async def test_several_levels_are_one_change_that_undoes(self, oauth, wired_app):
        connection = await _connection(oauth, wired_app)
        path = f"/api/v1/connections/{connection}/levels"

        resp = await _request(
            oauth,
            wired_app,
            "user-member",
            "PUT",
            path,
            {
                "levels": {"loop.launch": "notify", "note.add": "ask"},
                "reason": "I watch launches myself",
            },
        )

        levels = _levels(resp)
        assert levels["loop.launch"] == "notify" and levels["note.add"] == "ask"
        assert await _stored() == {"loop.launch": "notify", "note.add": "ask"}
        change = await wired_app.svc.get_change(TENANT_A, resp.json()["change_id"])
        assert change["kind"] == "connection.levels"
        assert change["target_type"] == "connection"
        assert change["before"] == {"name": "Claude Code", "levels": {}}
        assert change["after"] == {
            "name": "Claude Code",
            "levels": {"loop.launch": "notify", "note.add": "ask"},
        }
        assert change["reason"] == "I watch launches myself"

        listed = await _request(
            oauth, wired_app, "user-member", "GET", "/api/v1/connections"
        )
        assert listed.json()["connections"][0]["levels_changed"] == [
            {"kind": "note.add", "level": "ask", "default": "own"},
            {"kind": "loop.launch", "level": "notify", "default": "ask"},
        ]

        undone = await _request(
            oauth,
            wired_app,
            "user-member",
            "POST",
            f"/api/v1/changes/{change['id']}/undo",
            {"reason": "back to the defaults"},
        )
        assert undone.status_code == 200, undone.text
        assert undone.json()["kind"] == "connection.levels"
        assert await _stored() == {}

    async def test_a_later_change_merges_and_defaults_reset_everything(
        self, oauth, wired_app
    ):
        connection = await _connection(oauth, wired_app)
        path = f"/api/v1/connections/{connection}/levels"
        await _request(
            oauth,
            wired_app,
            "user-member",
            "PUT",
            path,
            {"levels": {"loop.launch": "own"}},
        )
        await _request(
            oauth,
            wired_app,
            "user-member",
            "PUT",
            path,
            {"levels": {"loop.retire": "notify"}},
        )
        assert await _stored() == {"loop.launch": "own", "loop.retire": "notify"}

        reset = await _request(
            oauth, wired_app, "user-member", "PUT", path, {"defaults": True}
        )

        assert _levels(reset) == autonomy.DEFAULTS
        assert await _stored() == {}

    async def test_setting_what_is_already_set_records_nothing(self, oauth, wired_app):
        connection = await _connection(oauth, wired_app)

        resp = await _request(
            oauth,
            wired_app,
            "user-member",
            "PUT",
            f"/api/v1/connections/{connection}/levels",
            {"levels": {"loop.launch": "ask"}},
        )

        assert resp.json()["change_id"] is None

    async def test_an_admin_cant_set_another_persons_levels(self, oauth, wired_app):
        members = await _connection(oauth, wired_app)

        resp = await _request(
            oauth,
            wired_app,
            "user-admin",
            "PUT",
            f"/api/v1/connections/{members}/levels",
            {"levels": {"loop.launch": "own"}},
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "CONNECTION_LEVELS_FORBIDDEN"
        assert await _stored() == {}

    async def test_an_admin_cant_undo_another_persons_levels(self, oauth, wired_app):
        connection = await _connection(oauth, wired_app)
        resp = await _request(
            oauth,
            wired_app,
            "user-member",
            "PUT",
            f"/api/v1/connections/{connection}/levels",
            {"levels": {"loop.launch": "own"}},
        )

        undone = await _request(
            oauth,
            wired_app,
            "user-admin",
            "POST",
            f"/api/v1/changes/{resp.json()['change_id']}/undo",
            {},
        )

        assert undone.status_code == 403
        assert await _stored() == {"loop.launch": "own"}

    async def test_a_read_an_old_kind_or_an_unknown_level_is_refused(
        self, oauth, wired_app
    ):
        connection = await _connection(oauth, wired_app)
        path = f"/api/v1/connections/{connection}/levels"

        for body in (
            {"levels": {"loop.read": "own"}},
            {"levels": {"gate.patch": "own"}},
            {"levels": {"loop.launch": "never"}},
            {"levels": {"loop.launch": "own"}, "defaults": True},
            {},
        ):
            resp = await _request(oauth, wired_app, "user-member", "PUT", path, body)
            assert resp.status_code == 422, body

    async def test_a_revoked_connections_levels_go_with_it(self, oauth, wired_app):
        connection = await _connection(oauth, wired_app)
        await _request(
            oauth,
            wired_app,
            "user-member",
            "PUT",
            f"/api/v1/connections/{connection}/levels",
            {"levels": {"loop.launch": "own"}},
        )

        await _request(
            oauth,
            wired_app,
            "user-member",
            "DELETE",
            f"/api/v1/connections/{connection}",
        )

        assert await _stored() == {}

    async def test_a_connection_actor_is_refused(self, oauth, wired_app):
        connection = await _connection(oauth, wired_app)

        with pytest.raises(ConnectionLevelsForbiddenError):
            await wired_app.svc.connections.set_levels(
                TENANT_A,
                connection,
                {"loop.launch": "own"},
                actor=Actor.connection(
                    "user-member", connection_id=connection, client_name="Claude Code"
                ),
                role="member",
            )
        assert await _stored() == {}

    async def test_an_api_key_is_refused(self, oauth, wired_app):
        connection = await _connection(oauth, wired_app)
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-member", api_key_id="key-1")
        try:
            for method, body in (("GET", None), ("PUT", {"defaults": True})):
                resp = await _request(
                    oauth,
                    wired_app,
                    "user-member",
                    method,
                    f"/api/v1/connections/{connection}/levels",
                    body,
                )
                assert resp.status_code == 403
        finally:
            overrides.pop(get_actor, None)
