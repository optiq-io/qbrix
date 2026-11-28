"""integration tests for qbrix next starting fresh.

invariants verified:
  with next on, nothing today's pools, experiments and gates recorded shows in
  next's changes: not the list, its counts, the summary, a read by id or an
  undo, while a loop's changes still do. every write to them, and the old
  select and feedback, is refused with 410 over http (grpc in
  integration/grpc/test_next_fresh.py), saying to create a loop; reads still answer. with next off they
  work as today.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

import proxysvc.config

from proxysvc.core.error import REPLACED_BY_LOOPS
from proxysvc.next import next_routes

TENANT = "dev-tenant"

PURCHASE = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
    "window_seconds": 172800,
}
OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
]


async def _seed_today(client) -> dict:
    """a pool, an experiment and its gate, each changed once, made with next off."""
    pool = await client.post(
        "/api/v1/pools",
        json={"name": "old-pool", "arms": [{"name": "a"}, {"name": "b"}]},
    )
    assert pool.status_code == 201, pool.text
    pool_id = pool.json()["id"]
    renamed = await client.patch(f"/api/v1/pools/{pool_id}", json={"name": "renamed"})
    assert renamed.status_code == 200, renamed.text
    experiment = await client.post(
        "/api/v1/experiments",
        json={
            "name": "old-exp",
            "pool_id": pool_id,
            "policy": "RandomPolicy",
            "policy_params": {},
            "enabled": True,
        },
    )
    assert experiment.status_code == 201, experiment.text
    experiment_id = experiment.json()["id"]
    paused = await client.patch(
        f"/api/v1/experiments/{experiment_id}", json={"enabled": False}
    )
    assert paused.status_code == 200, paused.text
    gate = await client.post(
        f"/api/v1/gates/{experiment_id}",
        json={"enabled": True, "rollout_percentage": 50.0, "rules": []},
    )
    assert gate.status_code == 201, gate.text
    return {"pool": pool_id, "experiment": experiment_id}


@pytest_asyncio.fixture
async def today(client, wired_app, app_with_db, monkeypatch):
    """today's objects with their changes, then next switched on."""
    seeded = await _seed_today(client)
    changes = [
        change
        for target_type, target_id in (
            ("pool", seeded["pool"]),
            ("experiment", seeded["experiment"]),
            ("gate", seeded["experiment"]),
        )
        for change in await wired_app.svc.list_changes(TENANT, target_type, target_id)
    ]
    assert {c["kind"] for c in changes} >= {
        "pool.create",
        "pool.update",
        "experiment.create",
        "experiment.update",
        "gate.create",
    }

    monkeypatch.setattr(proxysvc.config.settings, "next_enabled", True)
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    resp = await client.post("/api/v1/metrics", json=PURCHASE)
    assert resp.status_code == 201, resp.text
    yield {**seeded, "changes": changes}
    app.router.routes[:] = routes


class TestHidden:
    async def test_the_list_and_counts_hold_only_next(self, client, today):
        loop = await client.post(
            "/api/v1/loops",
            json={"name": "Checkout", "metric": "purchase", "options": OPTIONS},
        )
        assert loop.status_code == 201, loop.text

        listed = (await client.get("/api/v1/changes")).json()["changes"]
        counted = (await client.get("/api/v1/changes/counts")).json()
        summary = (await client.get("/api/v1/summary")).json()

        assert {entry["kind"] for entry in listed} == {"metric.create", "loop.create"}
        assert counted["total"] == 2
        assert summary["changes"]["total"] == 2

    async def test_an_old_change_reads_and_undoes_as_not_found(self, client, today):
        for change in today["changes"]:
            read = await client.get(f"/api/v1/changes/{change['id']}")
            undo = await client.post(f"/api/v1/changes/{change['id']}/undo")

            assert read.status_code == 404, change["kind"]
            assert undo.status_code == 404, change["kind"]
            assert undo.json()["code"] == "CHANGE_NOT_FOUND"


OLD_WRITES = [
    ("post", "/api/v1/pools", {"name": "p", "arms": [{"name": "a"}]}),
    ("patch", "/api/v1/pools/{pool}", {"name": "x"}),
    ("delete", "/api/v1/pools/{pool}", None),
    ("post", "/api/v1/experiments", {"name": "e", "pool_id": "{pool}"}),
    ("patch", "/api/v1/experiments/{experiment}", {"enabled": True}),
    ("post", "/api/v1/experiments/{experiment}/reset", None),
    ("delete", "/api/v1/experiments/{experiment}", None),
    ("post", "/api/v1/gates/{experiment}", {"enabled": True}),
    ("put", "/api/v1/gates/{experiment}", {"enabled": True}),
    ("patch", "/api/v1/gates/{experiment}", {"enabled": False}),
    ("delete", "/api/v1/gates/{experiment}", None),
    ("post", "/api/v1/agent/select", {"experiment_id": "{experiment}"}),
    ("post", "/api/v1/agent/feedback", {"request_id": "r", "reward": 1}),
]


class TestRefused:
    @pytest.mark.parametrize("method,path,body", OLD_WRITES)
    async def test_an_old_write_is_gone(self, client, today, method, path, body):
        path = path.format(**today)
        if body is not None:
            body = {
                k: v.format(**today) if isinstance(v, str) else v
                for k, v in body.items()
            }
        kwargs = {"json": body} if body is not None else {}

        resp = await client.request(method.upper(), path, **kwargs)

        assert resp.status_code == 410, resp.text
        assert resp.json() == {"code": "REPLACED_BY_LOOPS", "detail": REPLACED_BY_LOOPS}

    async def test_reads_still_answer(self, client, today):
        for path in (
            f"/api/v1/pools/{today['pool']}",
            f"/api/v1/experiments/{today['experiment']}",
            f"/api/v1/gates/{today['experiment']}",
            "/api/v1/experiments",
        ):
            assert (await client.get(path)).status_code == 200, path

    async def test_nothing_was_written(self, client, wired_app, today):
        await client.patch(f"/api/v1/pools/{today['pool']}", json={"name": "x"})

        pool = await wired_app.svc.get_pool(TENANT, today["pool"])
        assert pool["name"] == "renamed"
