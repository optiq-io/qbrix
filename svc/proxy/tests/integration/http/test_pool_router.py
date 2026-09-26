"""http integration tests for pool router.

invariants verified:
  scenario 1: POST /pools → 201 commits db row, emits audit pool.created
  scenario 2: GET /pools/{id} returns arms sorted by index ascending
  scenario 3: cross-tenant GET returns 404, not 403 (existence not leaked)
  scenario 4: DELETE pool with experiments → 409 with experiment names in message
  scenario 5: DELETE clean pool → 200 + pool.deleted audit event
  scenario 6: PATCH name → pool.updated audit event contains changed_fields=["name"]
"""

from __future__ import annotations

import pytest

from qbrixstore.event import AuditEvent

import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Pool

from svc.proxy.tests.integration.http.conftest import as_tenant


class TestCreatePool:
    async def test_create_pool_commits_row_and_emits_audit(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: POST /pools writes to postgres and publishes pool.created
        audit event with the correct arm_count payload.  if either the db
        write or the audit publish regresses, this test catches it.
        """
        body = {
            "name": "spike-pool",
            "arms": [
                {"name": "control", "metadata": {}},
                {"name": "variant", "metadata": {}},
            ],
        }

        response = await client.post("/api/v1/pools", json=body)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "spike-pool"
        assert len(data["arms"]) == 2
        pool_id = data["id"]
        assert pool_id  # non-empty id assigned by db

        # db row exists and belongs to dev-tenant (set by dev-bypass middleware)
        async with _session_module.get_session() as session:
            from sqlalchemy import select

            result = await session.execute(select(Pool).where(Pool.id == pool_id))
            row = result.scalar_one_or_none()

        assert row is not None
        assert row.name == "spike-pool"
        assert row.tenant_id == "dev-tenant"

        # audit event published with correct shape
        await wired_app.events.drain()
        assert len(wired_app.audit_spy.events) == 1
        event = wired_app.audit_spy.events[0]
        assert isinstance(event, AuditEvent)
        assert event.name == "pool.created"
        assert event.tenant_id == "dev-tenant"
        assert event.payload["arm_count"] == 2
        assert event.resource_id == pool_id


class TestGetPool:
    async def test_get_pool_returns_arms_sorted_by_index(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: GET /pools/{id} response always returns arms sorted by index
        ascending, regardless of the order arms were provided at creation time.
        the frontend depends on this ordering to render the correct arm at each
        position.

        note: PoolRepository.create assigns index=i (enumerate position), so the
        index order matches insertion order.  _pool_to_dict then sorts by arm.index.
        this test verifies the sort is present in the http response.
        """
        # arms intentionally out of alphabetical order; indices assigned positionally
        # (z→0, a→1, m→2).  GET must return them sorted 0,1,2 regardless.
        body = {
            "name": "sort-test-pool",
            "arms": [
                {"name": "z", "metadata": {}},
                {"name": "a", "metadata": {}},
                {"name": "m", "metadata": {}},
            ],
        }
        create_resp = await client.post("/api/v1/pools", json=body)
        assert create_resp.status_code == 201
        pool_id = create_resp.json()["id"]

        get_resp = await client.get(f"/api/v1/pools/{pool_id}")

        assert get_resp.status_code == 200
        arms = get_resp.json()["arms"]
        assert len(arms) == 3
        indices = [arm["index"] for arm in arms]
        assert indices == sorted(indices), f"arms not sorted by index: {indices}"
        # verify the positional assignment: z gets index 0, a gets 1, m gets 2
        assert arms[0]["name"] == "z"
        assert arms[0]["index"] == 0
        assert arms[1]["name"] == "a"
        assert arms[1]["index"] == 1
        assert arms[2]["name"] == "m"
        assert arms[2]["index"] == 2


class TestCrossTenantIsolation:
    async def test_cross_tenant_get_returns_404_not_403(
        self, client, wired_app, app_with_db, tenant_a, tenant_b
    ):
        """
        invariant: a tenant cannot discover that a pool belonging to another
        tenant exists.  the response must be 404, not 403 — returning 403
        would leak existence information across tenant boundaries.
        """
        # create pool as tenant_a
        with as_tenant(wired_app.app, tenant_id=tenant_a.id, user_id="user-a"):
            create_resp = await client.post(
                "/api/v1/pools",
                json={
                    "name": "tenant-a-pool",
                    "arms": [{"name": "ctrl", "metadata": {}}],
                },
            )
        assert create_resp.status_code == 201
        pool_id = create_resp.json()["id"]

        # attempt to read that pool as tenant_b — must be 404, not 403
        with as_tenant(wired_app.app, tenant_id=tenant_b.id, user_id="user-b"):
            get_resp = await client.get(f"/api/v1/pools/{pool_id}")

        assert get_resp.status_code == 404, (
            f"expected 404 for cross-tenant get, got {get_resp.status_code}. "
            "if this is 403, the router is leaking pool existence across tenants."
        )


class TestDeletePool:
    async def test_delete_pool_with_experiments_returns_409(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: attempting to delete a pool that has linked experiments must
        return 409 (conflict) with a message that references the blocking
        experiment names.  this prevents silent data loss by forcing the caller
        to clean up experiments first.
        """
        # create pool
        pool_resp = await client.post(
            "/api/v1/pools",
            json={
                "name": "pool-with-exp",
                "arms": [
                    {"name": "ctrl", "metadata": {}},
                    {"name": "var", "metadata": {}},
                ],
            },
        )
        assert pool_resp.status_code == 201
        pool_id = pool_resp.json()["id"]

        # link an experiment to that pool using RandomPolicy (no required params)
        exp_resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "blocking-experiment",
                "pool_id": pool_id,
                "policy": "RandomPolicy",
                "policy_params": {},
                "enabled": True,
            },
        )
        assert exp_resp.status_code == 201

        # attempt to delete the pool — must get 409
        delete_resp = await client.delete(f"/api/v1/pools/{pool_id}")

        assert delete_resp.status_code == 409
        detail = delete_resp.json().get("detail", "")
        assert (
            "blocking-experiment" in detail
        ), f"expected blocking experiment name in 409 detail, got: {detail!r}"

    async def test_delete_clean_pool_returns_200_and_emits_audit(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: deleting a pool with no linked experiments returns 200 and
        emits a pool.deleted audit event.  if the audit publish is dropped, the
        event log will have gaps that break compliance and observability.
        """
        # create pool (no experiments)
        pool_resp = await client.post(
            "/api/v1/pools",
            json={
                "name": "clean-pool",
                "arms": [{"name": "only-arm", "metadata": {}}],
            },
        )
        assert pool_resp.status_code == 201
        pool_id = pool_resp.json()["id"]
        # reset spy so we only see the delete audit event
        wired_app.audit_spy.events.clear()

        delete_resp = await client.delete(f"/api/v1/pools/{pool_id}")

        assert delete_resp.status_code == 200

        # pool.deleted audit event must be present
        await wired_app.events.drain()
        audit_events = [
            e for e in wired_app.audit_spy.events if e.name == "pool.deleted"
        ]
        assert len(audit_events) == 1
        event = audit_events[0]
        assert isinstance(event, AuditEvent)
        assert event.resource_id == pool_id
        assert event.tenant_id == "dev-tenant"

        # db row should be gone
        async with _session_module.get_session() as session:
            from sqlalchemy import select

            result = await session.execute(select(Pool).where(Pool.id == pool_id))
            row = result.scalar_one_or_none()
        assert row is None


class TestUpdatePool:
    async def test_patch_name_emits_audit_with_changed_fields(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: PATCH /pools/{id} with a name change emits a pool.updated
        audit event whose payload contains changed_fields=["name"].  this
        ensures the event log reflects the actual mutation rather than a
        generic "something changed" signal — callers use changed_fields to
        decide whether to invalidate caches or re-sync downstream state.
        """
        # create pool
        pool_resp = await client.post(
            "/api/v1/pools",
            json={
                "name": "original",
                "arms": [{"name": "arm-0", "metadata": {}}],
            },
        )
        assert pool_resp.status_code == 201
        pool_id = pool_resp.json()["id"]
        # reset spy so only the update audit event is captured
        wired_app.audit_spy.events.clear()

        patch_resp = await client.patch(
            f"/api/v1/pools/{pool_id}",
            json={"name": "renamed"},
        )

        assert patch_resp.status_code == 200
        assert patch_resp.json()["name"] == "renamed"

        # find the pool.updated audit event
        await wired_app.events.drain()
        updated_events = [
            e for e in wired_app.audit_spy.events if e.name == "pool.updated"
        ]
        assert (
            len(updated_events) == 1
        ), f"expected 1 pool.updated event, got {len(updated_events)}"
        event = updated_events[0]
        assert isinstance(event, AuditEvent)
        assert event.resource_id == pool_id
        assert event.tenant_id == "dev-tenant"
        assert event.payload.get("changed_fields") == [
            "name"
        ], f"expected changed_fields=['name'], got: {event.payload!r}"
