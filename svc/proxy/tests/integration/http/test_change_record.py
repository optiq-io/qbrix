"""http integration tests for the change record.

invariants verified:
  every pool, experiment and gate write leaves exactly one change, with the
  member who made it, the request id, before and after, and, for experiments,
  what each one had learned. a write that fails leaves neither the object
  change nor a record of it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func
from sqlalchemy import select

import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Pool
from qbrixstore.redis.client import Learning

from proxysvc.mod.change.repository import ChangeRepository

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"


async def _changes(wired_app, target_type: str, target_id: str) -> list[dict]:
    return list(
        reversed(await wired_app.svc.list_changes(TENANT, target_type, target_id))
    )


async def _count_changes() -> int:
    async with _session_module.get_session() as session:
        return (await session.execute(select(func.count(Change.id)))).scalar_one()


async def _create_pool(client, name: str = "change-pool") -> dict:
    resp = await client.post(
        "/api/v1/pools",
        json={"name": name, "arms": [{"name": "control"}, {"name": "variant"}]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_experiment(client, pool_id: str, **overrides) -> dict:
    body = {
        "name": "change-exp",
        "pool_id": pool_id,
        "policy": "BetaTSPolicy",
        "policy_params": {},
        "enabled": True,
        **overrides,
    }
    resp = await client.post("/api/v1/experiments", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed_learning(redis, experiment_id: str, applied: int) -> None:
    await redis.set_params(
        TENANT, experiment_id, {"num_arms": 2, "alpha": [3, 9], "beta": [1, 1]}
    )
    await redis.client.set(
        redis._learning_key(TENANT, experiment_id),
        Learning(params=None, applied=applied, last_id="7-0").encode_record(),
    )


class TestPoolChanges:
    async def test_create_update_delete_each_record_one_change(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        pool_id = pool["id"]

        resp = await client.patch(f"/api/v1/pools/{pool_id}", json={"name": "renamed"})
        assert resp.status_code == 200, resp.text
        resp = await client.delete(f"/api/v1/pools/{pool_id}")
        assert resp.status_code == 200, resp.text

        create, update, delete = await _changes(wired_app, "pool", pool_id)

        assert create["kind"] == "pool.create"
        assert create["before"] is None
        assert create["after"]["name"] == "change-pool"
        assert [arm["name"] for arm in create["after"]["arms"]] == [
            "control",
            "variant",
        ]

        assert update["kind"] == "pool.update"
        assert update["before"]["name"] == "change-pool"
        assert update["after"]["name"] == "renamed"

        assert delete["kind"] == "pool.delete"
        assert delete["before"]["name"] == "renamed"
        assert delete["after"] is None

        for change in (create, update, delete):
            assert change["actor"] == {
                "kind": "member",
                "user_id": "dev-user",
                "connection_id": None,
                "client_name": None,
                "api_key_id": None,
            }
            assert change["learning"] is None
            assert change["status"] == "applied"

    async def test_an_absent_snapshot_is_sql_null(self, client, wired_app, app_with_db):
        pool = await _create_pool(client)

        async with _session_module.get_session() as session:
            change = (
                await session.execute(
                    select(Change).where(
                        Change.target_id == pool["id"],
                        Change.before.is_(None),
                        Change.learning.is_(None),
                    )
                )
            ).scalar_one_or_none()
        assert change is not None

    async def test_a_missing_pool_records_nothing(self, client, wired_app, app_with_db):
        resp = await client.patch("/api/v1/pools/missing", json={"name": "x"})
        assert resp.status_code == 404
        resp = await client.delete("/api/v1/pools/missing")
        assert resp.status_code == 404
        assert await _count_changes() == 0


class TestExperimentChanges:
    async def test_create_records_the_experiment_and_its_gate(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(
            client, pool["id"], feature_gate={"enabled": True, "rollout_percentage": 40}
        )

        (create,) = await _changes(wired_app, "experiment", exp["id"])

        assert create["kind"] == "experiment.create"
        assert create["after"]["policy"] == "BetaTSPolicy"
        assert (
            create["after"]["feature_gate"]["experiment"]["rollout"]["percentage"] == 40
        )
        assert create["learning"] is None

    async def test_update_records_before_after_and_learning(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        await _seed_learning(wired_app.svc._redis, exp["id"], applied=12)

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}", json={"enabled": False}
        )
        assert resp.status_code == 200, resp.text

        _, update = await _changes(wired_app, "experiment", exp["id"])

        assert update["kind"] == "experiment.update"
        assert update["before"]["enabled"] is True
        assert update["after"]["enabled"] is False
        assert update["learning"] == {
            exp["id"]: {
                "params": {"num_arms": 2, "alpha": [3, 9], "beta": [1, 1]},
                "applied": 12,
                "last_id": "7-0",
            }
        }

    async def test_reset_records_what_was_learned_then_clears_it(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"], enabled=False)
        redis = wired_app.svc._redis
        await _seed_learning(redis, exp["id"], applied=8)

        resp = await client.post(f"/api/v1/experiments/{exp['id']}/reset")
        assert resp.status_code == 200, resp.text

        _, reset = await _changes(wired_app, "experiment", exp["id"])

        assert reset["kind"] == "experiment.reset"
        assert reset["learning"][exp["id"]]["applied"] == 8
        assert reset["before"] == reset["after"]
        assert await redis.read_learning(TENANT, exp["id"]) == Learning(params=None)

    async def test_a_failed_reset_leaves_no_record(
        self, client, wired_app, app_with_db, monkeypatch
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"], enabled=False)
        redis = wired_app.svc._redis
        await _seed_learning(redis, exp["id"], applied=8)

        async def _fail(*_args, **_kwargs):
            raise RuntimeError("redis down")

        monkeypatch.setattr(redis, "reset_learning", _fail)

        with pytest.raises(RuntimeError):
            await client.post(f"/api/v1/experiments/{exp['id']}/reset")

        kinds = [c["kind"] for c in await _changes(wired_app, "experiment", exp["id"])]
        assert kinds == ["experiment.create"]

    async def test_delete_records_the_experiment_and_its_learning(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        await _seed_learning(wired_app.svc._redis, exp["id"], applied=5)

        resp = await client.delete(f"/api/v1/experiments/{exp['id']}")
        assert resp.status_code == 200, resp.text

        _, delete = await _changes(wired_app, "experiment", exp["id"])

        assert delete["kind"] == "experiment.delete"
        assert delete["before"]["id"] == exp["id"]
        assert delete["after"] is None
        assert delete["learning"][exp["id"]]["applied"] == 5

    async def test_meta_experiment_carries_its_learners(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(
            client, pool["id"], policy="auto", policy_params={"reward_type": "binary"}
        )
        learner_ids = exp["policy_params"]["learners"]
        assert learner_ids

        resp = await client.delete(f"/api/v1/experiments/{exp['id']}")
        assert resp.status_code == 200, resp.text

        create, delete = await _changes(wired_app, "experiment", exp["id"])

        assert [l["id"] for l in create["after"]["learners"]] == learner_ids
        assert [l["id"] for l in delete["before"]["learners"]] == learner_ids
        assert set(delete["learning"]) == {exp["id"], *learner_ids}


class TestGateChanges:
    async def test_every_gate_write_records_one_change(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        exp_id = exp["id"]

        resp = await client.post(
            f"/api/v1/gates/{exp_id}", json={"enabled": True, "rollout_percentage": 50}
        )
        assert resp.status_code == 201, resp.text
        resp = await client.put(
            f"/api/v1/gates/{exp_id}", json={"enabled": True, "rollout_percentage": 70}
        )
        assert resp.status_code == 200, resp.text
        resp = await client.patch(
            f"/api/v1/gates/{exp_id}", json={"rollout_percentage": 90}
        )
        assert resp.status_code == 200, resp.text
        resp = await client.delete(f"/api/v1/gates/{exp_id}")
        assert resp.status_code == 200, resp.text

        changes = await _changes(wired_app, "gate", exp_id)

        assert [c["kind"] for c in changes] == [
            "gate.create",
            "gate.replace",
            "gate.patch",
            "gate.delete",
        ]
        rollouts = [
            (
                c["before"] and c["before"]["experiment"]["rollout"]["percentage"],
                c["after"] and c["after"]["experiment"]["rollout"]["percentage"],
            )
            for c in changes
        ]
        assert rollouts == [(None, 50), (50, 70), (70, 90), (90, None)]


class TestAtomicity:
    async def test_a_failed_record_rolls_back_the_write(
        self, client, wired_app, app_with_db, monkeypatch
    ):
        async def _fail(*_args, **_kwargs):
            raise RuntimeError("change log down")

        monkeypatch.setattr(ChangeRepository, "record", _fail)

        resp = await client.post(
            "/api/v1/pools", json={"name": "doomed", "arms": [{"name": "a"}]}
        )
        assert resp.status_code >= 500

        async with _session_module.get_session() as session:
            rows = (await session.execute(select(Pool))).scalars().all()
        assert rows == []
        assert await _count_changes() == 0


class TestRequestId:
    async def test_a_sane_inbound_id_is_kept_on_the_change_and_the_response(
        self, client, wired_app, app_with_db
    ):
        resp = await client.post(
            "/api/v1/pools",
            json={"name": "traced", "arms": [{"name": "a"}]},
            headers={"X-Request-ID": "req-abc.123"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.headers["x-request-id"] == "req-abc.123"

        (change,) = await _changes(wired_app, "pool", resp.json()["id"])
        assert change["request_id"] == "req-abc.123"

    @pytest.mark.parametrize("inbound", [None, "has spaces", "x" * 65])
    async def test_otherwise_one_is_minted(
        self, client, wired_app, app_with_db, inbound
    ):
        headers = {"X-Request-ID": inbound} if inbound else {}
        resp = await client.post(
            "/api/v1/pools",
            json={"name": "minted", "arms": [{"name": "a"}]},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        minted = resp.headers["x-request-id"]
        assert minted != inbound
        assert len(minted) == 32

        (change,) = await _changes(wired_app, "pool", resp.json()["id"])
        assert change["request_id"] == minted


class TestActor:
    async def test_the_member_is_who_the_request_authenticated_as(
        self, client, wired_app, app_with_db
    ):
        with as_tenant(wired_app.app, tenant_id=TENANT, user_id="user-42"):
            pool = await _create_pool(client)

        (change,) = await _changes(wired_app, "pool", pool["id"])
        assert change["actor"]["user_id"] == "user-42"
