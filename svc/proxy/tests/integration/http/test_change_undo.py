"""integration tests for undoing a recorded change.

invariants verified:
  an undo is a new change that puts the target back to the undone change's
  before, in postgres and in the redis record, and undoing the undo returns it
  to after. a reset's undo restores exactly what was learned and records how
  many later outcomes it dropped. undo is refused, never merged, when a later
  change moved what it would restore, when it was already undone, or when the
  kind can't be undone.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Change
from qbrixstore.redis.client import Learning

from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeNotUndoableError
from proxysvc.core.error import ExperimentRunningError
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.gate.repository import FeatureGateRepository

TENANT = "dev-tenant"
UNDOER = Actor.member("user-undo", request_id="req-undo")

CONTEXT_SCHEMA = [
    {"name": "device", "type": "categorical", "values": ["mobile", "desktop"]},
    {"name": "price", "type": "numeric", "min": 0, "max": 200},
]


async def _create_pool(client, name: str = "undo-pool") -> dict:
    resp = await client.post(
        "/api/v1/pools",
        json={"name": name, "arms": [{"name": "control"}, {"name": "variant"}]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_experiment(client, pool_id: str, **overrides) -> dict:
    body = {
        "name": "undo-exp",
        "pool_id": pool_id,
        "policy": "BetaTSPolicy",
        "policy_params": {},
        "enabled": True,
        **overrides,
    }
    resp = await client.post("/api/v1/experiments", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _patch_experiment(client, experiment_id: str, body: dict) -> dict:
    resp = await client.patch(f"/api/v1/experiments/{experiment_id}", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _latest(wired_app, target_type: str, target_id: str) -> dict:
    (change,) = await wired_app.svc.list_changes(
        TENANT, target_type, target_id, limit=1
    )
    return change


async def _undo(wired_app, change_id: str, reason: str | None = None) -> dict:
    return await wired_app.svc.undo_change(
        TENANT, change_id, actor=UNDOER, reason=reason
    )


def _experiment_state(experiment: dict) -> dict:
    return {
        key: experiment[key] for key in ("name", "enabled", "policy", "policy_params")
    }


async def _gate(experiment_id: str) -> dict | None:
    async with _session_module.get_session() as session:
        repo = FeatureGateRepository(session, TENANT)
        gate = await repo.get(experiment_id)
        if gate is None:
            return None
        return _unversioned(repo.to_config(gate).model_dump(mode="json"))


async def _cached_gate(wired_app, experiment_id: str) -> dict | None:
    config = await wired_app.svc.get_gate_config(TENANT, experiment_id)
    return _unversioned(config.model_dump(mode="json")) if config else None


def _unversioned(config: dict | None) -> dict | None:
    """sqlite drops a datetime's zone, so periods compare as utc."""
    if config is None:
        return None
    drop = ("version", "updated_at")
    experiment = {k: v for k, v in config["experiment"].items() if k not in drop}
    period = experiment["schedule"]["period"]
    experiment["schedule"]["period"] = {
        **period,
        "start": period["start"] and period["start"].removesuffix("Z"),
        "end": period["end"] and period["end"].removesuffix("Z"),
    }
    return {
        **{k: v for k, v in config.items() if k not in drop},
        "experiment": experiment,
    }


def _counting(ids: list[str]):
    def train(experiment, current: Learning) -> Learning:
        n = (current.params or {}).get("n", 0) + len(ids)
        return current.advance({"n": n}, ids)

    return train


async def _train(redis, experiment_id: str, ids: list[str]) -> None:
    await redis.apply_learning(TENANT, experiment_id, _counting(ids), lambda p: None)


class TestExperimentUpdate:
    async def test_pause_round_trips(self, client, wired_app, app_with_db):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        redis = wired_app.svc._redis
        await _patch_experiment(client, exp["id"], {"enabled": False})
        pause = await _latest(wired_app, "experiment", exp["id"])

        undo = await _undo(wired_app, pause["id"], reason="paused by mistake")

        assert undo["kind"] == "experiment.update"
        assert undo["undoes_id"] == pause["id"]
        assert undo["reason"] == "paused by mistake"
        assert undo["actor"]["user_id"] == "user-undo"
        assert undo["request_id"] == "req-undo"
        assert undo["before"]["enabled"] is False
        assert undo["after"]["enabled"] is True
        current = await wired_app.svc.get_experiment(TENANT, exp["id"])
        assert current["enabled"] is True
        assert (await redis.get_experiment(TENANT, exp["id"]))["enabled"] is True
        assert (await wired_app.svc.get_change(TENANT, pause["id"]))[
            "status"
        ] == "undone"

        await _undo(wired_app, undo["id"])

        current = await wired_app.svc.get_experiment(TENANT, exp["id"])
        assert current["enabled"] is False
        assert (await redis.get_experiment(TENANT, exp["id"]))["enabled"] is False

    async def test_policy_params_with_a_context_schema_round_trip(
        self, client, wired_app, app_with_db
    ):
        """the stored form carries the derived dim, which a patch would reject."""
        pool = await _create_pool(client)
        exp = await _create_experiment(
            client,
            pool["id"],
            policy="LinUCBPolicy",
            policy_params={"alpha": 1.5, "context_schema": CONTEXT_SCHEMA},
        )
        before = _experiment_state(exp)
        after = _experiment_state(
            await _patch_experiment(
                client,
                exp["id"],
                {"policy_params": {"alpha": 3.0, "context_schema": CONTEXT_SCHEMA}},
            )
        )
        update = await _latest(wired_app, "experiment", exp["id"])

        undo = await _undo(wired_app, update["id"])

        restored = await wired_app.svc.get_experiment(TENANT, exp["id"])
        assert _experiment_state(restored) == before
        record = await wired_app.svc._redis.get_experiment(TENANT, exp["id"])
        assert record["policy_params"] == before["policy_params"]

        await _undo(wired_app, undo["id"])

        redone = await wired_app.svc.get_experiment(TENANT, exp["id"])
        assert _experiment_state(redone) == after

    async def test_restores_only_the_fields_the_change_changed(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        await _patch_experiment(client, exp["id"], {"policy_params": {"seed": 7}})
        tune = await _latest(wired_app, "experiment", exp["id"])
        await _patch_experiment(client, exp["id"], {"enabled": False})

        await _undo(wired_app, tune["id"])

        current = await wired_app.svc.get_experiment(TENANT, exp["id"])
        assert current["policy_params"] == {}
        assert current["enabled"] is False

    async def test_refused_after_a_later_change_to_the_same_field(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        await _patch_experiment(client, exp["id"], {"enabled": False})
        pause = await _latest(wired_app, "experiment", exp["id"])
        await _patch_experiment(client, exp["id"], {"enabled": True})
        resume = await _latest(wired_app, "experiment", exp["id"])

        with pytest.raises(ChangeConflictError) as err:
            await _undo(wired_app, pause["id"])

        assert resume["id"] in str(err.value)
        assert "experiment.update" in str(err.value)
        assert (await wired_app.svc.get_change(TENANT, pause["id"]))[
            "status"
        ] == "applied"


class TestExperimentReset:
    async def _reset(self, client, wired_app, exp_id: str) -> dict:
        resp = await client.post(f"/api/v1/experiments/{exp_id}/reset")
        assert resp.status_code == 200, resp.text
        return await _latest(wired_app, "experiment", exp_id)

    async def test_restores_what_was_learned_exactly(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"], enabled=False)
        redis = wired_app.svc._redis
        await _train(redis, exp["id"], ["1-0", "2-0", "3-0"])
        learned = await redis.read_learning(TENANT, exp["id"])
        reset = await self._reset(client, wired_app, exp["id"])

        undo = await _undo(wired_app, reset["id"])

        assert undo["kind"] == "experiment.restore"
        assert undo["undoes_id"] == reset["id"]
        assert await redis.read_learning(TENANT, exp["id"]) == learned
        assert undo["learning"] == {
            exp["id"]: {"params": None, "applied": 0, "last_id": "0-0", "dropped": 0}
        }
        wired_app.svc._cortex_client.flush_batch.assert_awaited_with(exp["id"])

    async def test_outcomes_learned_since_are_dropped_and_counted(
        self, client, wired_app, app_with_db
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"], enabled=False)
        redis = wired_app.svc._redis
        await _train(redis, exp["id"], ["1-0", "2-0"])
        learned = await redis.read_learning(TENANT, exp["id"])
        reset = await self._reset(client, wired_app, exp["id"])
        await _train(redis, exp["id"], ["5-0", "6-0", "7-0"])
        since_reset = await redis.read_learning(TENANT, exp["id"])

        undo = await _undo(wired_app, reset["id"])

        assert await redis.read_learning(TENANT, exp["id"]) == learned
        assert undo["learning"][exp["id"]] == {
            "params": since_reset.params,
            "applied": 3,
            "last_id": "7-0",
            "dropped": 3,
        }

        await _train(redis, exp["id"], ["8-0"])
        redo = await _undo(wired_app, undo["id"])

        assert redo["kind"] == "experiment.restore"
        assert await redis.read_learning(TENANT, exp["id"]) == since_reset
        assert redo["learning"][exp["id"]]["dropped"] == 1

    async def test_refused_while_live(self, client, wired_app, app_with_db):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"], enabled=False)
        redis = wired_app.svc._redis
        await _train(redis, exp["id"], ["1-0"])
        reset = await self._reset(client, wired_app, exp["id"])
        await _patch_experiment(client, exp["id"], {"enabled": True})
        await _train(redis, exp["id"], ["4-0"])

        with pytest.raises(ExperimentRunningError, match="pause"):
            await _undo(wired_app, reset["id"])

        assert (await redis.read_learning(TENANT, exp["id"])).applied == 1
        assert (await wired_app.svc.get_change(TENANT, reset["id"]))[
            "status"
        ] == "applied"

        await _patch_experiment(client, exp["id"], {"enabled": False})
        undo = await _undo(wired_app, reset["id"])

        assert (await redis.read_learning(TENANT, exp["id"])).last_id == "1-0"
        assert undo["learning"][exp["id"]]["dropped"] == 1

    async def test_refused_after_a_later_reset(self, client, wired_app, app_with_db):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"], enabled=False)
        redis = wired_app.svc._redis
        await _train(redis, exp["id"], ["1-0"])
        first = await self._reset(client, wired_app, exp["id"])
        await _train(redis, exp["id"], ["2-0"])
        second = await self._reset(client, wired_app, exp["id"])

        with pytest.raises(ChangeConflictError, match=second["id"]):
            await _undo(wired_app, first["id"])

    async def test_a_failed_restore_leaves_no_record(
        self, client, wired_app, app_with_db, monkeypatch
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"], enabled=False)
        redis = wired_app.svc._redis
        await _train(redis, exp["id"], ["1-0"])
        reset = await self._reset(client, wired_app, exp["id"])

        async def _fail(*_args, **_kwargs):
            raise RuntimeError("redis down")

        monkeypatch.setattr(redis, "restore_learning", _fail)

        with pytest.raises(RuntimeError):
            await _undo(wired_app, reset["id"])

        assert (await _latest(wired_app, "experiment", exp["id"]))["id"] == reset["id"]
        assert (await wired_app.svc.get_change(TENANT, reset["id"]))[
            "status"
        ] == "applied"


class TestGate:
    GATE = {
        "enabled": True,
        "rollout_percentage": 40,
        "schedule_start": "2026-01-01T00:00:00+00:00",
        "active_hours_start": "09:00",
        "active_hours_end": "17:00",
        "timezone": "Europe/Amsterdam",
        "rules": [{"key": "country", "operator": "equals", "value": "NL"}],
    }

    async def _setup(self, client, wired_app) -> str:
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        resp = await client.post(f"/api/v1/gates/{exp['id']}", json=self.GATE)
        assert resp.status_code == 201, resp.text
        return exp["id"]

    async def test_create_round_trips(self, client, wired_app, app_with_db):
        exp_id = await self._setup(client, wired_app)
        created = await _gate(exp_id)
        create = await _latest(wired_app, "gate", exp_id)

        undo = await _undo(wired_app, create["id"])

        assert undo["kind"] == "gate.delete"
        assert await _gate(exp_id) is None
        assert await _cached_gate(wired_app, exp_id) is None

        redo = await _undo(wired_app, undo["id"])

        assert redo["kind"] == "gate.create"
        assert await _gate(exp_id) == created
        assert await _cached_gate(wired_app, exp_id) == created

    async def test_delete_round_trips(self, client, wired_app, app_with_db):
        exp_id = await self._setup(client, wired_app)
        existing = await _gate(exp_id)
        resp = await client.delete(f"/api/v1/gates/{exp_id}")
        assert resp.status_code == 200, resp.text
        delete = await _latest(wired_app, "gate", exp_id)

        undo = await _undo(wired_app, delete["id"])

        assert undo["kind"] == "gate.create"
        assert await _gate(exp_id) == existing
        assert await _cached_gate(wired_app, exp_id) == existing

        await _undo(wired_app, undo["id"])

        assert await _gate(exp_id) is None

    @pytest.mark.parametrize("method", ["put", "patch"])
    async def test_replace_and_patch_round_trip_nulls_included(
        self, client, wired_app, app_with_db, method
    ):
        exp_id = await self._setup(client, wired_app)
        before = await _gate(exp_id)
        assert before["experiment"]["schedule"]["period"]["end"] is None
        body = {
            "enabled": False,
            "rollout_percentage": 80,
            "schedule_start": None,
            "schedule_end": "2027-01-01T00:00:00+00:00",
            "active_hours_start": None,
            "active_hours_end": None,
            "timezone": "UTC",
            "rules": [],
        }
        resp = await getattr(client, method)(f"/api/v1/gates/{exp_id}", json=body)
        assert resp.status_code == 200, resp.text
        after = await _gate(exp_id)
        change = await _latest(wired_app, "gate", exp_id)

        undo = await _undo(wired_app, change["id"])

        assert undo["kind"] == "gate.replace"
        assert await _gate(exp_id) == before
        assert await _cached_gate(wired_app, exp_id) == before

        await _undo(wired_app, undo["id"])

        assert await _gate(exp_id) == after

    async def test_refused_after_a_later_gate_change(
        self, client, wired_app, app_with_db
    ):
        exp_id = await self._setup(client, wired_app)
        create = await _latest(wired_app, "gate", exp_id)
        resp = await client.patch(
            f"/api/v1/gates/{exp_id}", json={"rollout_percentage": 10}
        )
        assert resp.status_code == 200, resp.text
        patch = await _latest(wired_app, "gate", exp_id)

        with pytest.raises(ChangeConflictError, match=patch["id"]):
            await _undo(wired_app, create["id"])

        assert (await _gate(exp_id))["experiment"]["rollout"]["percentage"] == 10

    async def test_allowed_when_later_changes_left_it_as_the_change_did(
        self, client, wired_app, app_with_db
    ):
        """a period written with an offset reads back in utc; same instant."""
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        exp_id = exp["id"]
        gate = {**self.GATE, "schedule_start": "2026-01-01T02:00:00+02:00"}
        resp = await client.post(f"/api/v1/gates/{exp_id}", json=gate)
        assert resp.status_code == 201, resp.text
        create = await _latest(wired_app, "gate", exp_id)
        for rollout in (10, 40):
            resp = await client.patch(
                f"/api/v1/gates/{exp_id}", json={"rollout_percentage": rollout}
            )
            assert resp.status_code == 200, resp.text

        undo = await _undo(wired_app, create["id"])

        assert undo["kind"] == "gate.delete"
        assert await _gate(exp_id) is None


class TestPool:
    async def test_rename_round_trips(self, client, wired_app, app_with_db):
        pool = await _create_pool(client, name="before")
        resp = await client.patch(f"/api/v1/pools/{pool['id']}", json={"name": "after"})
        assert resp.status_code == 200, resp.text
        rename = await _latest(wired_app, "pool", pool["id"])

        undo = await _undo(wired_app, rename["id"])

        assert undo["kind"] == "pool.update"
        assert (await wired_app.svc.get_pool(TENANT, pool["id"]))["name"] == "before"

        await _undo(wired_app, undo["id"])

        assert (await wired_app.svc.get_pool(TENANT, pool["id"]))["name"] == "after"


class TestRefusals:
    async def test_a_change_is_undone_once(self, client, wired_app, app_with_db):
        pool = await _create_pool(client, name="before")
        await client.patch(f"/api/v1/pools/{pool['id']}", json={"name": "after"})
        rename = await _latest(wired_app, "pool", pool["id"])
        undo = await _undo(wired_app, rename["id"])

        with pytest.raises(ChangeConflictError, match=undo["id"]):
            await _undo(wired_app, rename["id"])

    async def test_a_concurrent_change_refuses_the_undo_at_write_time(
        self, client, wired_app, app_with_db
    ):
        """the check is repeated inside the undo's own transaction."""
        pool = await _create_pool(client, name="before")
        await client.patch(f"/api/v1/pools/{pool['id']}", json={"name": "after"})
        rename = await _latest(wired_app, "pool", pool["id"])
        await client.patch(f"/api/v1/pools/{pool['id']}", json={"name": "after"})
        landed = await _latest(wired_app, "pool", pool["id"])

        with pytest.raises(ChangeConflictError, match=landed["id"]):
            await wired_app.svc._pool_service.update_pool(
                TENANT,
                pool["id"],
                actor=UNDOER,
                undoing=Undoing(change_id=rename["id"], latest_id=rename["id"]),
                name="before",
            )

        assert (await wired_app.svc.get_pool(TENANT, pool["id"]))["name"] == "after"

    @pytest.mark.parametrize("kind", ["create", "delete"])
    async def test_creates_and_deletes_are_not_undoable(
        self, client, wired_app, app_with_db, kind
    ):
        pool = await _create_pool(client)
        exp = await _create_experiment(client, pool["id"])
        if kind == "delete":
            resp = await client.delete(f"/api/v1/experiments/{exp['id']}")
            assert resp.status_code == 200, resp.text
        change = await _latest(wired_app, "experiment", exp["id"])
        assert change["kind"] == f"experiment.{kind}"
        assert change["undoable"] is False

        with pytest.raises(ChangeNotUndoableError):
            await _undo(wired_app, change["id"])

    async def test_undoable_kinds_say_so(self, client, wired_app, app_with_db):
        pool = await _create_pool(client)
        await client.patch(f"/api/v1/pools/{pool['id']}", json={"name": "x"})

        create, rename = reversed(
            await wired_app.svc.list_changes(TENANT, "pool", pool["id"])
        )

        assert create["undoable"] is False
        assert rename["undoable"] is True

    async def test_a_missing_change_returns_none(self, client, wired_app, app_with_db):
        assert await _undo(wired_app, "missing") is None

    async def test_another_tenants_change_is_missing(
        self, client, wired_app, app_with_db, tenant_b
    ):
        pool = await _create_pool(client, name="before")
        await client.patch(f"/api/v1/pools/{pool['id']}", json={"name": "after"})
        rename = await _latest(wired_app, "pool", pool["id"])

        assert (
            await wired_app.svc.undo_change("tenant-b", rename["id"], actor=UNDOER)
            is None
        )
        async with _session_module.get_session() as session:
            status = (
                await session.execute(
                    select(Change.status).where(Change.id == rename["id"])
                )
            ).scalar_one()
        assert status == "applied"
