"""integration tests for pins, a qbrix next surface.

invariants verified:
  a pin belongs to one person: it lists for them in the order they pinned, with
  its target's name, key and state, and for nobody else. pinning and unpinning
  are idempotent. a target from another workspace looks the same as one that
  doesn't exist. a retired or deleted target leaves the list. a viewer can pin,
  an api key can't, and a pin records no change.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

import proxysvc.config
from proxysvc.core.actor import Actor
from proxysvc.next import next_routes
from proxysvc.transport.http.auth.dependencies import get_actor
from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import Pin
from qbrixstore.postgres.session import get_session

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
OTHER_TENANT = "other-tenant"

PURCHASE = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
}

HEADLINE = {
    "name": "Checkout headline",
    "metric": "purchase",
    "options": [
        {"name": "Control", "config": {"text": "Buy now"}},
        {"name": "Urgency", "config": {"text": "Only today"}},
    ],
}


@pytest_asyncio.fixture
async def pins(wired_app, client, next_enabled):
    """the client, with the next routes mounted on the app for this test only."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    yield client
    app.router.routes[:] = routes


async def _metric(client) -> dict:
    resp = await client.post("/api/v1/metrics", json=PURCHASE)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _loop(client) -> dict:
    await _metric(client)
    resp = await client.post("/api/v1/loops", json=HEADLINE)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _pin(client, kind: str, ref: str) -> None:
    resp = await client.put(f"/api/v1/pins/{kind}/{ref}")
    assert resp.status_code == 204, resp.text


async def _listed(client) -> list[dict]:
    resp = await client.get("/api/v1/pins")
    assert resp.status_code == 200, resp.text
    return resp.json()["pins"]


async def _set_state(loop_id: str, state: str) -> None:
    async with get_session() as session:
        await session.execute(
            update(Loop).where(Loop.id == loop_id).values(state=state)
        )


class TestList:
    async def test_starts_empty(self, pins):
        assert await _listed(pins) == []

    async def test_a_loop_carries_its_name_key_and_state(self, pins):
        loop = await _loop(pins)

        await _pin(pins, "loop", loop["id"])

        assert await _listed(pins) == [
            {
                "kind": "loop",
                "ref": loop["id"],
                "name": "Checkout headline",
                "key": loop["key"],
                "state": "draft",
            }
        ]

    async def test_a_metric_has_no_state(self, pins):
        metric = await _metric(pins)

        await _pin(pins, "metric", metric["id"])

        assert await _listed(pins) == [
            {
                "kind": "metric",
                "ref": metric["id"],
                "name": "purchase",
                "key": "purchase",
                "state": None,
            }
        ]

    async def test_keeps_the_order_they_were_pinned_in(self, pins):
        loop = await _loop(pins)
        resp = await pins.get("/api/v1/metrics/purchase")
        metric = resp.json()

        await _pin(pins, "metric", metric["id"])
        await _pin(pins, "loop", loop["id"])

        assert [p["kind"] for p in await _listed(pins)] == ["metric", "loop"]

    async def test_a_paused_loop_is_listed_as_paused(self, pins):
        loop = await _loop(pins)
        await _pin(pins, "loop", loop["id"])

        await _set_state(loop["id"], "paused")

        assert (await _listed(pins))[0]["state"] == "paused"

    async def test_a_retired_loop_leaves_the_list(self, pins):
        loop = await _loop(pins)
        await _pin(pins, "loop", loop["id"])

        await _set_state(loop["id"], "retired")

        assert await _listed(pins) == []

    async def test_a_deleted_loop_leaves_the_list(self, pins):
        loop = await _loop(pins)
        await _pin(pins, "loop", loop["id"])

        async with get_session() as session:
            await session.execute(delete(Loop).where(Loop.id == loop["id"]))

        assert await _listed(pins) == []


class TestPin:
    async def test_pinning_twice_keeps_one_pin(self, pins):
        loop = await _loop(pins)

        await _pin(pins, "loop", loop["id"])
        await _pin(pins, "loop", loop["id"])

        assert len(await _listed(pins)) == 1

    async def test_losing_a_race_to_pin_is_not_an_error(self, pins, monkeypatch):
        loop = await _loop(pins)

        async def _taken(self, *args):
            raise IntegrityError("insert", {}, Exception("uq_pin_user_kind_ref"))

        monkeypatch.setattr("proxysvc.mod.pin.service.PinRepository.create", _taken)

        await _pin(pins, "loop", loop["id"])

    async def test_a_target_that_doesnt_exist_is_refused(self, pins):
        resp = await pins.put("/api/v1/pins/loop/nope")

        assert resp.status_code == 404
        assert resp.json()["code"] == "PIN_TARGET_NOT_FOUND"

    async def test_another_workspaces_target_looks_the_same(self, wired_app, pins):
        loop = await _loop(pins)
        missing = await pins.put("/api/v1/pins/loop/nope")

        with as_tenant(wired_app.app, tenant_id=OTHER_TENANT, user_id="user-b"):
            resp = await pins.put(f"/api/v1/pins/loop/{loop['id']}")

        assert resp.status_code == 404
        assert resp.json()["code"] == missing.json()["code"]

    async def test_an_unknown_kind_is_refused(self, pins):
        resp = await pins.put("/api/v1/pins/experiment/abc")

        assert resp.status_code == 422

    async def test_records_no_change(self, wired_app, pins):
        loop = await _loop(pins)
        before = await wired_app.svc.list_changes(TENANT, "loop", loop["id"])

        await _pin(pins, "loop", loop["id"])
        await pins.delete(f"/api/v1/pins/loop/{loop['id']}")

        after = await wired_app.svc.list_changes(TENANT, "loop", loop["id"])
        assert after == before
        async with get_session() as session:
            changes = await session.execute(select(func.count()).select_from(Change))
            assert changes.scalar_one() == 2  # the metric's creation and the loop's


class TestUnpin:
    async def test_removes_the_pin(self, pins):
        loop = await _loop(pins)
        await _pin(pins, "loop", loop["id"])

        resp = await pins.delete(f"/api/v1/pins/loop/{loop['id']}")

        assert resp.status_code == 204
        assert await _listed(pins) == []

    async def test_unpinning_what_isnt_pinned_is_fine(self, pins):
        resp = await pins.delete("/api/v1/pins/loop/nope")

        assert resp.status_code == 204

    async def test_only_touches_your_own_pin(self, wired_app, pins):
        loop = await _loop(pins)
        with as_tenant(wired_app.app, tenant_id=TENANT, user_id="user-a"):
            await _pin(pins, "loop", loop["id"])

        with as_tenant(wired_app.app, tenant_id=TENANT, user_id="user-c"):
            await pins.delete(f"/api/v1/pins/loop/{loop['id']}")

        with as_tenant(wired_app.app, tenant_id=TENANT, user_id="user-a"):
            assert len(await _listed(pins)) == 1


class TestWho:
    async def test_another_person_never_sees_it(self, wired_app, pins):
        loop = await _loop(pins)
        with as_tenant(wired_app.app, tenant_id=TENANT, user_id="user-a"):
            await _pin(pins, "loop", loop["id"])

        with as_tenant(wired_app.app, tenant_id=TENANT, user_id="user-c"):
            assert await _listed(pins) == []

    async def test_a_viewer_can_pin(self, wired_app, pins):
        loop = await _loop(pins)

        with as_tenant(wired_app.app, tenant_id=TENANT, role="viewer"):
            await _pin(pins, "loop", loop["id"])
            assert len(await _listed(pins)) == 1

    async def test_an_api_key_is_refused(self, wired_app, pins):
        loop = await _loop(pins)
        overrides = wired_app.app.dependency_overrides
        overrides[get_actor] = lambda: Actor.member("user-x", api_key_id="key-1")
        try:
            listed = await pins.get("/api/v1/pins")
            pinned = await pins.put(f"/api/v1/pins/loop/{loop['id']}")
            unpinned = await pins.delete(f"/api/v1/pins/loop/{loop['id']}")
        finally:
            del overrides[get_actor]

        assert listed.status_code == 403
        assert pinned.status_code == 403
        assert unpinned.status_code == 403
        async with get_session() as session:
            count = await session.execute(select(func.count()).select_from(Pin))
            assert count.scalar_one() == 0
