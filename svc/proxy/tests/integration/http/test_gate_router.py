"""http integration tests for gate router.

invariants verified:
  scenario 1: POST gate config → 201; GET round-trips via DB and redis (read-after-write)
  scenario 2: PUT updates → invalidate called before set_config (no stale cache window)
  scenario 3: DELETE → 200, GET returns 404, redis key gone
  scenario 4: GET nonexistent gate → 404 via GateNotFoundException
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────


async def _create_pool(client, *, name: str = "gate-test-pool") -> str:
    """create a pool and return its id."""
    resp = await client.post(
        "/api/v1/pools",
        json={
            "name": name,
            "arms": [
                {"name": "control", "metadata": {}},
                {"name": "variant", "metadata": {}},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_experiment(client, pool_id: str, *, name: str = "gate-exp") -> str:
    """create a RandomPolicy experiment and return its id."""
    resp = await client.post(
        "/api/v1/experiments",
        json={
            "name": name,
            "pool_id": pool_id,
            "policy": "RandomPolicy",
            "policy_params": {},
            "enabled": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_gate(client, experiment_id: str, *, rollout: float = 100.0) -> dict:
    """POST a gate config and return the response json."""
    resp = await client.post(
        f"/api/v1/gates/{experiment_id}",
        json={
            "enabled": True,
            "rollout_percentage": rollout,
            "rules": [],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── scenario 1 ────────────────────────────────────────────────────────────────


class TestCreateGateConfig:
    async def test_create_gate_config_round_trips_via_db_and_redis(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: POST /gates/{experiment_id} writes to postgres and syncs to redis.
        subsequent GET returns the same config from cache, proving read-after-write
        consistency through both storage layers.
        """
        pool_id = await _create_pool(client, name="create-gate-pool")
        exp_id = await _create_experiment(client, pool_id, name="create-gate-exp")

        # clear audit spy so only gate events are visible
        wired_app.audit_spy.events.clear()

        post_resp = await client.post(
            f"/api/v1/gates/{exp_id}",
            json={
                "enabled": True,
                "rollout_percentage": 75.0,
                "rules": [],
            },
        )

        assert post_resp.status_code == 201, post_resp.text
        post_data = post_resp.json()
        assert post_data["experiment_id"] == exp_id
        assert post_data["enabled"] is True
        assert post_data["rollout_percentage"] == 75.0

        # GET must return the same config
        get_resp = await client.get(f"/api/v1/gates/{exp_id}")

        assert get_resp.status_code == 200, get_resp.text
        get_data = get_resp.json()
        assert get_data["experiment_id"] == exp_id
        assert get_data["enabled"] is True
        assert get_data["rollout_percentage"] == 75.0

        # redis key must exist with the correct gate data
        redis_key = f"qbrix:tenant:dev-tenant:gate:{exp_id}"
        raw = await wired_app.fake_redis.get(redis_key)
        assert (
            raw is not None
        ), f"expected redis key {redis_key!r} to be present after POST gate config"

        # audit event emitted for gate creation
        await wired_app.events.drain()
        gate_audit_events = [
            e for e in wired_app.audit_spy.events if e.name == "gate.created"
        ]
        assert len(gate_audit_events) == 1
        event = gate_audit_events[0]
        assert event.resource_id == exp_id
        assert event.tenant_id == "dev-tenant"


# ── scenario 2 ────────────────────────────────────────────────────────────────


class TestUpdateGateConfig:
    async def test_put_updates_config_and_invalidate_called_before_set(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: PUT /gates/{experiment_id} must call gate_service.invalidate()
        before gate_service.set_config() so there is no window where a reader
        can load the stale l1 cache entry.  if invalidate is skipped or reordered,
        the l1 cache can serve the old config to motorsvc after the update.

        verification strategy: wrap both methods on the live gate_svc with
        Mock(wraps=...) and attach them to a parent Mock so mock_calls ordering
        reflects the actual call sequence.
        """
        pool_id = await _create_pool(client, name="update-gate-pool")
        exp_id = await _create_experiment(client, pool_id, name="update-gate-exp")

        # create initial gate config
        await _create_gate(client, exp_id, rollout=50.0)

        # wrap gate_svc methods to track call order via a shared parent mock
        gate_svc = wired_app.gate_svc

        parent = Mock(name="cache_ops")

        original_invalidate = gate_svc.invalidate
        original_set_config = gate_svc.set_config

        gate_svc.invalidate = Mock(
            name="cache_ops.invalidate",
            wraps=original_invalidate,
        )
        gate_svc.set_config = AsyncMock(
            name="cache_ops.set_config",
            wraps=original_set_config,
        )
        parent.attach_mock(gate_svc.invalidate, "invalidate")
        parent.attach_mock(gate_svc.set_config, "set_config")

        try:
            put_resp = await client.put(
                f"/api/v1/gates/{exp_id}",
                json={
                    "enabled": True,
                    "rollout_percentage": 90.0,
                    "rules": [],
                },
            )

            assert put_resp.status_code == 200, put_resp.text
            assert put_resp.json()["rollout_percentage"] == 90.0

            # both methods must have been called
            gate_svc.invalidate.assert_called_once()
            gate_svc.set_config.assert_called_once()

            # invalidate must have been called before set_config
            call_names = [call[0] for call in parent.mock_calls]
            assert "invalidate" in call_names, "invalidate was not called during update"
            assert "set_config" in call_names, "set_config was not called during update"
            invalidate_pos = call_names.index("invalidate")
            set_config_pos = call_names.index("set_config")
            assert invalidate_pos < set_config_pos, (
                f"invalidate must be called before set_config to prevent stale cache reads. "
                f"got call order: {call_names}"
            )
        finally:
            # restore original methods
            gate_svc.invalidate = original_invalidate
            gate_svc.set_config = original_set_config

        # post-update GET must return the new config (not stale)
        get_resp = await client.get(f"/api/v1/gates/{exp_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["rollout_percentage"] == 90.0


# ── scenario 3 ────────────────────────────────────────────────────────────────


class TestDeleteGateConfig:
    async def test_delete_gate_config_returns_200_and_cleans_db_and_redis(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: DELETE /gates/{experiment_id} returns 200, removes the config
        from both postgres (subsequent GET returns 404) and redis (key gone).
        """
        pool_id = await _create_pool(client, name="delete-gate-pool")
        exp_id = await _create_experiment(client, pool_id, name="delete-gate-exp")
        await _create_gate(client, exp_id, rollout=100.0)

        # verify key exists in redis before delete
        redis_key = f"qbrix:tenant:dev-tenant:gate:{exp_id}"
        raw_before = await wired_app.fake_redis.get(redis_key)
        assert raw_before is not None, "gate redis key must exist before delete"

        # clear spy to isolate the delete audit event
        wired_app.audit_spy.events.clear()

        delete_resp = await client.delete(f"/api/v1/gates/{exp_id}")

        assert delete_resp.status_code == 200, delete_resp.text
        assert "deleted" in delete_resp.json().get("message", "").lower()

        # GET must now return 404 (GateNotFoundException)
        get_resp = await client.get(f"/api/v1/gates/{exp_id}")
        assert (
            get_resp.status_code == 404
        ), f"expected 404 after delete, got {get_resp.status_code}: {get_resp.text}"

        # redis key must be gone
        raw_after = await wired_app.fake_redis.get(redis_key)
        assert (
            raw_after is None
        ), f"expected redis key {redis_key!r} to be absent after delete"

        # gate.deleted audit event emitted
        await wired_app.events.drain()
        gate_deleted_events = [
            e for e in wired_app.audit_spy.events if e.name == "gate.deleted"
        ]
        assert len(gate_deleted_events) == 1
        event = gate_deleted_events[0]
        assert event.resource_id == exp_id
        assert event.tenant_id == "dev-tenant"


# ── scenario 4 ────────────────────────────────────────────────────────────────


class TestGetNonexistentGate:
    async def test_get_gate_for_experiment_without_config_returns_404(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: GET /gates/{experiment_id} when no gate config exists raises
        GateNotFoundException → HTTP 404.  the detail must reference the gate or
        experiment so callers can distinguish this from a missing experiment.
        """
        pool_id = await _create_pool(client, name="no-gate-pool")
        exp_id = await _create_experiment(client, pool_id, name="no-gate-exp")

        # no gate config created — GET must be 404
        get_resp = await client.get(f"/api/v1/gates/{exp_id}")

        assert (
            get_resp.status_code == 404
        ), f"expected 404 for missing gate config, got {get_resp.status_code}: {get_resp.text}"
        detail = get_resp.json().get("detail", "")
        assert detail, "404 response must include a detail message"
        # detail should mention gate or experiment context
        assert any(
            kw in detail.lower() for kw in ("gate", "experiment", "not found")
        ), f"expected 404 detail to mention gate/experiment/not found, got: {detail!r}"


# ── scenario 5 ────────────────────────────────────────────────────────────────


class TestEvaluateGateConfig:
    """POST /gates/{id}/evaluate — dry-run against a sample context.

    the endpoint exists so the console can show what the gate *will* do before
    anyone changes live traffic, so the invariants that matter are: it decides
    identically to the select path, and it writes nothing.
    """

    async def test_evaluate_reports_bandit_when_gate_does_not_intervene(
        self, client, app_with_db
    ):
        pool_id = await _create_pool(client, name="eval-bandit-pool")
        exp_id = await _create_experiment(client, pool_id, name="eval-bandit-exp")
        await _create_gate(client, exp_id, rollout=100.0)

        resp = await client.post(
            f"/api/v1/gates/{exp_id}/evaluate",
            json={"context_id": "u-1", "context_metadata": {"device": "mobile"}},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["eligible"] is True
        assert data["reason"] == "bandit"
        assert data["arm_id"] is None
        assert data["in_rollout"] is True

    async def test_evaluate_reports_the_committed_arm_at_zero_rollout(
        self, client, app_with_db
    ):
        """rollout 0 is how the console commits an arm — every context is out."""
        pool_id = await _create_pool(client, name="eval-commit-pool")
        exp_id = await _create_experiment(client, pool_id, name="eval-commit-exp")
        await _create_gate(client, exp_id, rollout=0.0)

        resp = await client.post(
            f"/api/v1/gates/{exp_id}/evaluate",
            json={"context_id": "u-1", "context_metadata": {}},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["eligible"] is False
        assert data["reason"] == "rollout"
        assert data["in_rollout"] is False

    async def test_evaluate_reports_every_rule_not_just_the_decisive_one(
        self, client, app_with_db
    ):
        pool_id = await _create_pool(client, name="eval-rules-pool")
        exp_id = await _create_experiment(client, pool_id, name="eval-rules-exp")

        resp = await client.post(
            f"/api/v1/gates/{exp_id}",
            json={
                "enabled": True,
                "rollout_percentage": 100.0,
                "rules": [
                    {"key": "device", "operator": "eq", "value": "desktop"},
                    {"key": "country", "operator": "eq", "value": "NL"},
                ],
            },
        )
        assert resp.status_code == 201, resp.text

        resp = await client.post(
            f"/api/v1/gates/{exp_id}/evaluate",
            json={
                "context_id": "u-1",
                "context_metadata": {"device": "mobile", "country": "NL"},
            },
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        rules = data["rules"]
        assert [r["matched"] for r in rules] == [False, True]
        # only the rule that actually decided the outcome is marked decisive
        assert [r["decisive"] for r in rules] == [False, True]
        assert data["reason"] == "rule"
        assert data["eligible"] is False

    async def test_evaluate_does_not_mutate_the_gate(self, client, app_with_db):
        pool_id = await _create_pool(client, name="eval-readonly-pool")
        exp_id = await _create_experiment(client, pool_id, name="eval-readonly-exp")
        before = await _create_gate(client, exp_id, rollout=42.0)

        await client.post(
            f"/api/v1/gates/{exp_id}/evaluate",
            json={"context_id": "u-1", "context_metadata": {}},
        )

        after = (await client.get(f"/api/v1/gates/{exp_id}")).json()
        assert after["rollout_percentage"] == before["rollout_percentage"]
        assert after["version"] == before["version"]

    async def test_evaluate_nonexistent_gate_returns_404(self, client, app_with_db):
        pool_id = await _create_pool(client, name="eval-404-pool")
        exp_id = await _create_experiment(client, pool_id, name="eval-404-exp")

        resp = await client.post(
            f"/api/v1/gates/{exp_id}/evaluate",
            json={"context_id": "u-1", "context_metadata": {}},
        )

        assert resp.status_code == 404, resp.text


# ── scenario 6 ────────────────────────────────────────────────────────────────


class TestCommitViaGate:
    """setting default_arm_id must survive the write, in the response *and* in
    the config that live traffic reads.

    regression: `update()` assigns the fk but `to_config()` reads the eager-
    loaded `default_arm` relationship, which sqlalchemy does not re-resolve on
    flush. the arm came back null while postgres held the right value — and the
    same empty config was cached, so at rollout 0 every request would have been
    served an arm with no id.
    """

    async def test_commit_persists_the_default_arm(self, client, app_with_db):
        pool_id = await _create_pool(client, name="commit-pool")
        exp_id = await _create_experiment(client, pool_id, name="commit-exp")
        arm_id = (await client.get(f"/api/v1/pools/{pool_id}")).json()["arms"][0]["id"]

        await _create_gate(client, exp_id, rollout=100.0)

        put = await client.put(
            f"/api/v1/gates/{exp_id}",
            json={
                "enabled": True,
                "rollout_percentage": 0.0,
                "default_arm_id": arm_id,
                "rules": [],
            },
        )

        assert put.status_code == 200, put.text
        assert put.json()["default_arm_id"] == arm_id
        assert put.json()["default_arm_name"] is not None

        # and it must still be there on a fresh read
        got = (await client.get(f"/api/v1/gates/{exp_id}")).json()
        assert got["default_arm_id"] == arm_id
        assert got["rollout_percentage"] == 0.0

    async def test_committed_arm_is_what_evaluate_reports(self, client, app_with_db):
        """the whole point of committing: out-of-rollout traffic gets that arm."""
        pool_id = await _create_pool(client, name="commit-eval-pool")
        exp_id = await _create_experiment(client, pool_id, name="commit-eval-exp")
        arm = (await client.get(f"/api/v1/pools/{pool_id}")).json()["arms"][0]

        await _create_gate(client, exp_id, rollout=100.0)
        await client.put(
            f"/api/v1/gates/{exp_id}",
            json={
                "enabled": True,
                "rollout_percentage": 0.0,
                "default_arm_id": arm["id"],
                "rules": [],
            },
        )

        resp = await client.post(
            f"/api/v1/gates/{exp_id}/evaluate",
            json={"context_id": "u-1", "context_metadata": {}},
        )

        data = resp.json()
        assert data["eligible"] is False
        assert data["reason"] == "rollout"
        assert data["arm_id"] == arm["id"]
        assert data["arm_name"] == arm["name"]

    async def test_create_with_a_default_arm_hydrates_it(self, client, app_with_db):
        pool_id = await _create_pool(client, name="commit-create-pool")
        exp_id = await _create_experiment(client, pool_id, name="commit-create-exp")
        arm_id = (await client.get(f"/api/v1/pools/{pool_id}")).json()["arms"][0]["id"]

        resp = await client.post(
            f"/api/v1/gates/{exp_id}",
            json={
                "enabled": True,
                "rollout_percentage": 0.0,
                "default_arm_id": arm_id,
                "rules": [],
            },
        )

        assert resp.status_code == 201, resp.text
        assert resp.json()["default_arm_id"] == arm_id

    async def test_resume_clears_the_commit(self, client, app_with_db):
        pool_id = await _create_pool(client, name="resume-pool")
        exp_id = await _create_experiment(client, pool_id, name="resume-exp")
        arm_id = (await client.get(f"/api/v1/pools/{pool_id}")).json()["arms"][0]["id"]

        await _create_gate(client, exp_id, rollout=100.0)
        await client.put(
            f"/api/v1/gates/{exp_id}",
            json={
                "enabled": True,
                "rollout_percentage": 0.0,
                "default_arm_id": arm_id,
                "rules": [],
            },
        )

        resumed = await client.put(
            f"/api/v1/gates/{exp_id}",
            json={
                "enabled": True,
                "rollout_percentage": 100.0,
                "default_arm_id": arm_id,
                "rules": [],
            },
        )
        assert resumed.status_code == 200, resumed.text

        resp = await client.post(
            f"/api/v1/gates/{exp_id}/evaluate",
            json={"context_id": "u-1", "context_metadata": {}},
        )
        # back on the learner
        assert resp.json()["eligible"] is True
        assert resp.json()["reason"] == "bandit"


# ── scenario 5 ────────────────────────────────────────────────────────────────


async def _create_full_gate(client, experiment_id: str, arm_id: str) -> dict:
    """POST a gate with every field populated, so a patch has something to lose."""
    resp = await client.post(
        f"/api/v1/gates/{experiment_id}",
        json={
            "enabled": True,
            "rollout_percentage": 20.0,
            "default_arm_id": arm_id,
            "schedule_start": "2026-01-01T00:00:00+00:00",
            "schedule_end": "2027-01-01T00:00:00+00:00",
            "active_hours_start": "09:00",
            "active_hours_end": "17:00",
            "timezone": "Europe/Amsterdam",
            "rules": [
                {
                    "key": "plan",
                    "operator": "eq",
                    "value": "enterprise",
                    "arm_id": arm_id,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestPatchGateConfig:
    """PATCH applies only the fields the caller sent.

    regression: `update` was PUT-only, and every SDK/console caller
    that omitted a field had it written back as the schema default. raising a
    rollout re-enabled a disabled gate, dropped the default arm, cleared every
    targeting rule and erased the schedule — silently, with a 200 and a
    healthy-looking body.
    """

    async def test_patching_the_rollout_leaves_every_other_field_alone(
        self, client, app_with_db
    ):
        pool_id = await _create_pool(client, name="patch-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-exp")
        arm_id = (await client.get(f"/api/v1/pools/{pool_id}")).json()["arms"][0]["id"]

        before = await _create_full_gate(client, exp_id, arm_id)

        resp = await client.patch(
            f"/api/v1/gates/{exp_id}", json={"rollout_percentage": 50.0}
        )

        assert resp.status_code == 200, resp.text
        after = resp.json()
        assert after["rollout_percentage"] == 50.0
        for field in (
            "enabled",
            "default_arm_id",
            "default_arm_name",
            "schedule_start",
            "schedule_end",
            "active_hours_start",
            "active_hours_end",
            "timezone",
            "rules",
        ):
            assert after[field] == before[field], f"{field} was not preserved"
        assert after["version"] == before["version"] + 1

        # and the same must hold on a fresh read, not just in the response body
        assert (await client.get(f"/api/v1/gates/{exp_id}")).json() == after

    async def test_patching_a_disabled_gate_does_not_reenable_it(
        self, client, app_with_db
    ):
        pool_id = await _create_pool(client, name="patch-disabled-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-disabled-exp")

        await _create_gate(client, exp_id, rollout=20.0)
        await client.patch(f"/api/v1/gates/{exp_id}", json={"enabled": False})

        resp = await client.patch(
            f"/api/v1/gates/{exp_id}", json={"rollout_percentage": 50.0}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is False

    async def test_explicit_null_clears_but_omission_preserves(
        self, client, app_with_db
    ):
        pool_id = await _create_pool(client, name="patch-null-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-null-exp")
        arm_id = (await client.get(f"/api/v1/pools/{pool_id}")).json()["arms"][0]["id"]

        await _create_full_gate(client, exp_id, arm_id)

        omitted = await client.patch(f"/api/v1/gates/{exp_id}", json={"enabled": True})
        assert omitted.json()["default_arm_id"] == arm_id
        assert omitted.json()["schedule_start"] is not None

        cleared = await client.patch(
            f"/api/v1/gates/{exp_id}",
            json={"default_arm_id": None, "schedule_start": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["default_arm_id"] is None
        assert cleared.json()["default_arm_name"] is None
        assert cleared.json()["schedule_start"] is None
        assert cleared.json()["schedule_end"] is not None

    async def test_omitting_rules_preserves_them_and_empty_list_clears(
        self, client, app_with_db
    ):
        pool_id = await _create_pool(client, name="patch-rules-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-rules-exp")
        arm_id = (await client.get(f"/api/v1/pools/{pool_id}")).json()["arms"][0]["id"]

        await _create_full_gate(client, exp_id, arm_id)

        kept = await client.patch(
            f"/api/v1/gates/{exp_id}", json={"rollout_percentage": 30.0}
        )
        assert len(kept.json()["rules"]) == 1
        assert kept.json()["rules"][0]["arm_id"] == arm_id

        replaced = await client.patch(
            f"/api/v1/gates/{exp_id}",
            json={"rules": [{"key": "country", "operator": "eq", "value": "NL"}]},
        )
        assert [r["key"] for r in replaced.json()["rules"]] == ["country"]

        emptied = await client.patch(f"/api/v1/gates/{exp_id}", json={"rules": []})
        assert emptied.json()["rules"] == []

    async def test_put_still_replaces_the_whole_config(self, client, app_with_db):
        """PATCH is the addition; PUT keeps its replace semantics."""
        pool_id = await _create_pool(client, name="put-replaces-pool")
        exp_id = await _create_experiment(client, pool_id, name="put-replaces-exp")
        arm_id = (await client.get(f"/api/v1/pools/{pool_id}")).json()["arms"][0]["id"]

        await _create_full_gate(client, exp_id, arm_id)

        resp = await client.put(
            f"/api/v1/gates/{exp_id}",
            json={"enabled": True, "rollout_percentage": 50.0, "rules": []},
        )

        assert resp.status_code == 200, resp.text
        after = resp.json()
        assert after["default_arm_id"] is None
        assert after["rules"] == []
        assert after["schedule_start"] is None
        assert after["timezone"] == "UTC"

    async def test_patch_invalidates_l1_before_writing_the_cache(
        self, client, wired_app, app_with_db
    ):
        """same no-stale-window invariant the PUT path carries."""
        pool_id = await _create_pool(client, name="patch-cache-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-cache-exp")
        await _create_gate(client, exp_id, rollout=50.0)

        gate_svc = wired_app.gate_svc
        parent = Mock(name="cache_ops")
        original_invalidate = gate_svc.invalidate
        original_set_config = gate_svc.set_config
        gate_svc.invalidate = Mock(wraps=original_invalidate)
        gate_svc.set_config = AsyncMock(wraps=original_set_config)
        parent.attach_mock(gate_svc.invalidate, "invalidate")
        parent.attach_mock(gate_svc.set_config, "set_config")

        try:
            resp = await client.patch(
                f"/api/v1/gates/{exp_id}", json={"rollout_percentage": 90.0}
            )
            assert resp.status_code == 200, resp.text

            call_names = [call[0] for call in parent.mock_calls]
            assert call_names.index("invalidate") < call_names.index("set_config")
        finally:
            gate_svc.invalidate = original_invalidate
            gate_svc.set_config = original_set_config

        assert (await client.get(f"/api/v1/gates/{exp_id}")).json()[
            "rollout_percentage"
        ] == 90.0

    async def test_patch_syncs_the_new_config_to_redis(
        self, client, wired_app, app_with_db
    ):
        pool_id = await _create_pool(client, name="patch-redis-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-redis-exp")
        await _create_gate(client, exp_id, rollout=50.0)

        await client.patch(f"/api/v1/gates/{exp_id}", json={"rollout_percentage": 90.0})

        raw = await wired_app.fake_redis.get(f"qbrix:tenant:dev-tenant:gate:{exp_id}")
        assert raw is not None
        assert '"percentage":90.0' in raw.replace(" ", "")

    async def test_patch_emits_an_audit_event_naming_the_changed_fields(
        self, client, wired_app, app_with_db
    ):
        pool_id = await _create_pool(client, name="patch-audit-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-audit-exp")
        await _create_gate(client, exp_id, rollout=50.0)
        wired_app.audit_spy.events.clear()

        await client.patch(
            f"/api/v1/gates/{exp_id}",
            json={"rollout_percentage": 90.0, "enabled": False},
        )

        await wired_app.events.drain()
        events = [e for e in wired_app.audit_spy.events if e.name == "gate.updated"]
        assert len(events) == 1
        assert events[0].resource_id == exp_id
        assert events[0].payload == {"fields": ["enabled", "rollout_percentage"]}

    async def test_patching_a_nonexistent_gate_returns_404(self, client, app_with_db):
        pool_id = await _create_pool(client, name="patch-404-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-404-exp")

        resp = await client.patch(
            f"/api/v1/gates/{exp_id}", json={"rollout_percentage": 50.0}
        )

        assert resp.status_code == 404, resp.text

    async def test_empty_patch_is_a_no_op_that_still_succeeds(
        self, client, app_with_db
    ):
        pool_id = await _create_pool(client, name="patch-empty-pool")
        exp_id = await _create_experiment(client, pool_id, name="patch-empty-exp")
        before = await _create_gate(client, exp_id, rollout=50.0)

        resp = await client.patch(f"/api/v1/gates/{exp_id}", json={})

        assert resp.status_code == 200, resp.text
        assert resp.json()["rollout_percentage"] == before["rollout_percentage"]
        assert resp.json()["version"] == before["version"] + 1

    @pytest.mark.parametrize(
        "body",
        [
            {"enabled": None},
            {"rollout_percentage": None},
            {"timezone": None},
            {"rules": None},
        ],
    )
    async def test_null_on_a_non_nullable_field_is_rejected(
        self, client, app_with_db, body
    ):
        """a null here would hit a NOT NULL violation; 422 says which field."""
        pool_id = await _create_pool(client, name=f"patch-422-{list(body)[0]}")
        exp_id = await _create_experiment(client, pool_id, name=f"e-{list(body)[0]}")
        await _create_gate(client, exp_id, rollout=50.0)

        resp = await client.patch(f"/api/v1/gates/{exp_id}", json=body)

        assert resp.status_code == 422, resp.text
