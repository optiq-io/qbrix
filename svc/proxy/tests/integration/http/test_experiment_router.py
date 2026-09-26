"""http integration tests for experiment router.

invariants verified:
  scenario 1: POST with valid policy params → 201, db row, experiment.created audit, redis key present
  scenario 2: POST with invalid policy_params, an empty policy, or an unbuildable
              auto portfolio → 400 InvalidPolicyParamsException (never 409)
  scenario 3: POST policy="auto" (meta-bandit) → parent + N learner experiments created
  scenario 6: DELETE learner experiment → 403 LearnerExperimentDeleteException
  scenario 7: DELETE regular experiment with gate → 200, redis cleaned, gate removed, audit emitted
  scenario 8: GET cross-tenant → 404, existence not leaked
  scenario 9: POST reset on a paused experiment → 200, params cleared, experiment.reset audit
  scenario 10: POST reset on a running experiment → 409 ExperimentRunningException
  scenario 11: POST reset on a missing experiment → 404
  scenario 12: POST with context_schema → dim derived, schema stored canonically
  scenario 13: PATCH altering or dropping context_schema → 409 ContextSchemaImmutableException
  scenario 14: PATCH altering or dropping dim → 409 ContextDimImmutableException
"""

from __future__ import annotations

from sqlalchemy import select

from qbrixstore.postgres.models import Experiment
from qbrixstore.event import AuditEvent

import qbrixstore.postgres.session as _session_module

from svc.proxy.tests.integration.http.conftest import as_tenant

# ── helpers ──────────────────────────────────────────────────────────────────


async def _create_pool(client, *, name: str = "test-pool") -> str:
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


async def _create_experiment(
    client,
    pool_id: str,
    *,
    name: str = "test-exp",
    policy: str = "BetaTSPolicy",
    policy_params: dict | None = None,
    enabled: bool = True,
) -> dict:
    """create an experiment and return the response json."""
    resp = await client.post(
        "/api/v1/experiments",
        json={
            "name": name,
            "pool_id": pool_id,
            "policy": policy,
            "policy_params": policy_params or {},
            "enabled": enabled,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── scenario 1 ────────────────────────────────────────────────────────────────


class TestCreateExperimentValid:
    async def test_create_with_valid_params_commits_row_and_emits_audit_and_syncs_redis(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: POST /experiments writes to postgres, publishes experiment.created
        audit event with the correct payload, and sets the experiment key in redis.
        BetaTSPolicy requires no user-configurable params so policy_params={} is valid.
        """
        pool_id = await _create_pool(client, name="create-test-pool")
        # clear any pool audit events so only the experiment event is visible
        wired_app.audit_spy.events.clear()

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "beta-experiment",
                "pool_id": pool_id,
                "policy": "BetaTSPolicy",
                "policy_params": {},
                "enabled": True,
            },
        )

        assert resp.status_code == 201
        data = resp.json()
        exp_id = data["id"]
        assert exp_id
        assert data["name"] == "beta-experiment"
        assert data["policy"] == "BetaTSPolicy"
        assert data["pool_id"] == pool_id
        assert data["enabled"] is True

        # db row exists with correct tenant
        async with _session_module.get_session() as session:
            result = await session.execute(
                select(Experiment).where(Experiment.id == exp_id)
            )
            row = result.scalar_one_or_none()

        assert row is not None
        assert row.name == "beta-experiment"
        assert row.tenant_id == "dev-tenant"
        assert row.policy == "BetaTSPolicy"

        # audit event published
        await wired_app.events.drain()
        audit_events = [
            e for e in wired_app.audit_spy.events if e.name == "experiment.created"
        ]
        assert len(audit_events) == 1
        event = audit_events[0]
        assert isinstance(event, AuditEvent)
        assert event.resource_id == exp_id
        assert event.tenant_id == "dev-tenant"
        assert event.payload["pool_id"] == pool_id
        assert event.payload["policy"] == "BetaTSPolicy"

        # redis key exists: _sync_experiment_to_redis uses set_experiment
        redis_data = await wired_app.svc._redis.get_experiment("dev-tenant", exp_id)
        assert redis_data is not None
        assert redis_data["id"] == exp_id


# ── scenario 2 ────────────────────────────────────────────────────────────────


class TestCreateExperimentInvalidParams:
    async def test_invalid_policy_params_returns_400(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: submitting EpsilonPolicy without its required fields (eps, gamma)
        raises BadPolicyParamsError → router maps it to InvalidPolicyParamsException
        → HTTP 400.  the detail must reference the bad param situation.
        """
        pool_id = await _create_pool(client, name="invalid-params-pool")

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "bad-params-exp",
                "pool_id": pool_id,
                # EpsilonPolicy requires eps and gamma (both required, no defaults)
                "policy": "EpsilonPolicy",
                "policy_params": {},
                "enabled": True,
            },
        )

        # InvalidPolicyParamsException extends BadRequestException → 400
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        # the message contains the policy name and describes the failure
        assert (
            "EpsilonPolicy" in detail or "eps" in detail or "invalid" in detail.lower()
        ), f"expected detail mentioning EpsilonPolicy or eps, got: {detail!r}"

    async def test_unknown_policy_returns_400(self, client, wired_app, app_with_db):
        """
        invariant: submitting a policy name that doesn't exist raises BadPolicyParamsError
        → 400 with a detail mentioning the unknown policy.
        """
        pool_id = await _create_pool(client, name="unknown-policy-pool")

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "unknown-policy-exp",
                "pool_id": pool_id,
                "policy": "DoesNotExistPolicy",
                "policy_params": {},
                "enabled": True,
            },
        )

        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert (
            "DoesNotExistPolicy" in detail or "unknown" in detail.lower()
        ), f"expected detail mentioning unknown policy, got: {detail!r}"

    async def test_empty_policy_returns_400_not_a_plan_limit(
        self, client, wired_app, app_with_db
    ):
        """a request-shape failure must not be reported as a billing problem."""
        pool_id = await _create_pool(client, name="empty-policy-pool")

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "empty-policy-exp",
                "pool_id": pool_id,
                "policy": "",
                "policy_params": {},
                "enabled": True,
            },
        )

        assert resp.status_code == 400, resp.text
        assert resp.json().get("code") == "INVALID_POLICY_PARAMS"
        assert "policy is required" in resp.json().get("detail", "")

    async def test_auto_without_a_width_returns_400_naming_the_width(
        self, client, wired_app, app_with_db
    ):
        """build_learners' ValueErrors reached the same trap as the empty policy."""
        pool_id = await _create_pool(client, name="auto-no-dim-pool")

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "auto-no-dim-exp",
                "pool_id": pool_id,
                "policy": "auto",
                "policy_params": {"reward_type": "binary", "use_context": True},
                "enabled": True,
            },
        )

        assert resp.status_code == 400, resp.text
        assert resp.json().get("code") == "INVALID_POLICY_PARAMS"
        assert "dim" in resp.json().get("detail", "")

    async def test_auto_with_an_invalid_reward_type_returns_400(
        self, client, wired_app, app_with_db
    ):
        pool_id = await _create_pool(client, name="auto-bad-reward-pool")

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "auto-bad-reward-exp",
                "pool_id": pool_id,
                "policy": "auto",
                "policy_params": {"reward_type": "not-a-reward-type"},
                "enabled": True,
            },
        )

        assert resp.status_code == 400, resp.text
        assert resp.json().get("code") == "INVALID_POLICY_PARAMS"


# ── scenario 3 ────────────────────────────────────────────────────────────────


class TestCreateMetaExperiment:
    async def test_auto_policy_creates_parent_and_learner_experiments(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: POST /experiments with policy="auto" creates:
          - a parent experiment with policy=MetaBanditPolicy
          - N learner experiments each with meta_experiment_id == parent.id
          - learner ids stored in parent policy_params["learners"]
          - all learner experiment redis keys present before the parent key
            (service.py syncs learners first, then parent at lines 365-366)
          - a single experiment.created audit event (for the parent only)

        using reward_type="binary", use_context=False yields 7 learners
        (verified by build_learners() call in isolation).
        """
        pool_id = await _create_pool(client, name="meta-pool")
        wired_app.audit_spy.events.clear()

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "auto-experiment",
                "pool_id": pool_id,
                "policy": "auto",
                "policy_params": {"reward_type": "binary"},
                "enabled": True,
            },
        )

        assert resp.status_code == 201, resp.text
        data = resp.json()
        parent_id = data["id"]
        assert data["policy"] == "MetaBanditPolicy"

        # learner ids are in policy_params
        learner_ids: list[str] = data["policy_params"]["learners"]
        assert (
            len(learner_ids) == 7
        ), f"expected 7 binary non-contextual learners, got {len(learner_ids)}"

        # all learner experiments exist in DB with correct meta_experiment_id
        async with _session_module.get_session() as session:
            for lid in learner_ids:
                result = await session.execute(
                    select(Experiment).where(Experiment.id == lid)
                )
                learner_row = result.scalar_one_or_none()
                assert learner_row is not None, f"learner {lid} not in db"
                assert learner_row.meta_experiment_id == parent_id, (
                    f"learner {lid} meta_experiment_id={learner_row.meta_experiment_id!r}, "
                    f"expected {parent_id!r}"
                )

        # all learner redis keys exist
        for lid in learner_ids:
            redis_data = await wired_app.svc._redis.get_experiment("dev-tenant", lid)
            assert redis_data is not None, f"redis key missing for learner {lid}"

        # parent redis key exists
        parent_redis = await wired_app.svc._redis.get_experiment(
            "dev-tenant", parent_id
        )
        assert parent_redis is not None

        # only one experiment.created audit event (for the parent)
        await wired_app.events.drain()
        created_events = [
            e for e in wired_app.audit_spy.events if e.name == "experiment.created"
        ]
        assert len(created_events) == 1
        event = created_events[0]
        assert event.resource_id == parent_id
        assert event.payload.get("mode") == "auto"
        assert event.payload.get("learners") == learner_ids


# ── scenario 6 ────────────────────────────────────────────────────────────────


class TestDeleteLearnerExperiment:
    async def test_delete_learner_experiment_returns_403(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: attempting to DELETE a learner experiment that belongs to a
        meta-bandit raises LearnerExperimentDeleteError → LearnerExperimentDeleteException
        → HTTP 403 (LearnerExperimentDeleteException extends ForbiddenException).
        """
        pool_id = await _create_pool(client, name="meta-delete-pool")

        # create meta experiment (policy="auto", binary)
        meta_resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "meta-for-delete-test",
                "pool_id": pool_id,
                "policy": "auto",
                "policy_params": {"reward_type": "binary"},
                "enabled": True,
            },
        )
        assert meta_resp.status_code == 201, meta_resp.text
        learner_ids: list[str] = meta_resp.json()["policy_params"]["learners"]
        assert learner_ids, "expected at least one learner id"

        # attempt to delete the first learner
        delete_resp = await client.delete(f"/api/v1/experiments/{learner_ids[0]}")

        # LearnerExperimentDeleteException extends ForbiddenException → 403
        assert delete_resp.status_code == 403, (
            f"expected 403 for learner experiment delete, got {delete_resp.status_code}: "
            f"{delete_resp.text}"
        )


# ── scenario 7 ────────────────────────────────────────────────────────────────


class TestDeleteRegularExperiment:
    async def test_delete_experiment_with_gate_cleans_redis_and_gate_and_emits_audit(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: DELETE /experiments/{id} on an experiment that has a feature gate:
          - returns 200
          - emits experiment.deleted audit event
          - removes the experiment key from redis
          - removes the gate key from redis (delete_experiment calls delete_config)
        """
        pool_id = await _create_pool(client, name="delete-gate-pool")

        # create experiment
        exp_resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "exp-with-gate",
                "pool_id": pool_id,
                "policy": "BetaTSPolicy",
                "policy_params": {},
                "enabled": True,
            },
        )
        assert exp_resp.status_code == 201, exp_resp.text
        exp_id = exp_resp.json()["id"]

        # attach a gate (POST /api/v1/gates/{experiment_id})
        gate_resp = await client.post(
            f"/api/v1/gates/{exp_id}",
            json={
                "enabled": True,
                "rollout_percentage": 100,
                "rules": [],
            },
        )
        assert gate_resp.status_code == 201, gate_resp.text

        # verify experiment key is in redis before delete
        before_data = await wired_app.svc._redis.get_experiment("dev-tenant", exp_id)
        assert before_data is not None

        # clear spy to isolate the delete audit event
        wired_app.audit_spy.events.clear()

        delete_resp = await client.delete(f"/api/v1/experiments/{exp_id}")

        assert delete_resp.status_code == 200, delete_resp.text

        # experiment.deleted audit event present
        await wired_app.events.drain()
        deleted_events = [
            e for e in wired_app.audit_spy.events if e.name == "experiment.deleted"
        ]
        assert len(deleted_events) == 1
        event = deleted_events[0]
        assert isinstance(event, AuditEvent)
        assert event.resource_id == exp_id
        assert event.tenant_id == "dev-tenant"

        # experiment key removed from redis
        after_data = await wired_app.svc._redis.get_experiment("dev-tenant", exp_id)
        assert after_data is None, "experiment redis key should be gone after delete"

        # gate key removed from redis
        # delete_experiment calls _gate_service.delete_config → redis.delete_gate_config
        gate_data = await wired_app.svc._redis.get_gate_config("dev-tenant", exp_id)
        assert (
            gate_data is None
        ), "gate redis key should be gone after experiment delete"


# ── scenario 8 ────────────────────────────────────────────────────────────────


class TestCrossTenantIsolation:
    async def test_cross_tenant_get_returns_404_not_403(
        self, client, wired_app, app_with_db, tenant_a, tenant_b
    ):
        """
        invariant: a tenant cannot discover that an experiment belonging to another
        tenant exists.  the response must be 404, not 403 — returning 403 would
        leak existence across tenant boundaries.
        """
        # create pool and experiment as tenant_a
        with as_tenant(wired_app.app, tenant_id=tenant_a.id, user_id="user-a"):
            pool_resp = await client.post(
                "/api/v1/pools",
                json={
                    "name": "tenant-a-pool",
                    "arms": [{"name": "ctrl", "metadata": {}}],
                },
            )
            assert pool_resp.status_code == 201
            pool_id = pool_resp.json()["id"]

            exp_resp = await client.post(
                "/api/v1/experiments",
                json={
                    "name": "tenant-a-experiment",
                    "pool_id": pool_id,
                    "policy": "BetaTSPolicy",
                    "policy_params": {},
                    "enabled": True,
                },
            )
            assert exp_resp.status_code == 201
            exp_id = exp_resp.json()["id"]

        # attempt to GET that experiment as tenant_b
        with as_tenant(wired_app.app, tenant_id=tenant_b.id, user_id="user-b"):
            get_resp = await client.get(f"/api/v1/experiments/{exp_id}")

        assert get_resp.status_code == 404, (
            f"expected 404 for cross-tenant get, got {get_resp.status_code}. "
            "if this is 403, the router is leaking experiment existence across tenants."
        )


# ── scenario 9 ────────────────────────────────────────────────────────────────


class TestResetExperiment:
    async def test_reset_paused_experiment_clears_params_and_emits_audit(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: POST /experiments/{id}/reset on a paused experiment returns 200,
        deletes the learned params blob in redis, and emits an experiment.reset audit.
        """
        pool_id = await _create_pool(client, name="reset-pool")
        exp = await _create_experiment(client, pool_id, name="reset-exp", enabled=False)
        exp_id = exp["id"]

        # seed a learned params blob in redis
        await wired_app.svc._redis.set_params(
            "dev-tenant", exp_id, {"num_arms": 2, "alpha": [9, 9], "beta": [1, 1]}
        )
        assert await wired_app.svc._redis.get_params("dev-tenant", exp_id) is not None

        wired_app.audit_spy.events.clear()

        resp = await client.post(f"/api/v1/experiments/{exp_id}/reset")

        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == exp_id

        # params blob removed
        assert await wired_app.svc._redis.get_params("dev-tenant", exp_id) is None

        # experiment.reset audit event emitted
        await wired_app.events.drain()
        reset_events = [
            e for e in wired_app.audit_spy.events if e.name == "experiment.reset"
        ]
        assert len(reset_events) == 1
        event = reset_events[0]
        assert isinstance(event, AuditEvent)
        assert event.resource_id == exp_id
        assert event.tenant_id == "dev-tenant"


# ── scenario 10 ───────────────────────────────────────────────────────────────


class TestResetRunningExperiment:
    async def test_reset_running_experiment_returns_409(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: resetting an enabled (running) experiment is rejected with 409
        (ExperimentRunningException) and the params blob is left untouched.
        """
        pool_id = await _create_pool(client, name="reset-running-pool")
        exp = await _create_experiment(
            client, pool_id, name="reset-running-exp", enabled=True
        )
        exp_id = exp["id"]

        await wired_app.svc._redis.set_params(
            "dev-tenant", exp_id, {"num_arms": 2, "alpha": [3, 3], "beta": [1, 1]}
        )

        resp = await client.post(f"/api/v1/experiments/{exp_id}/reset")

        assert resp.status_code == 409, resp.text
        # params untouched
        assert await wired_app.svc._redis.get_params("dev-tenant", exp_id) is not None


# ── scenario 11 ───────────────────────────────────────────────────────────────


class TestResetMissingExperiment:
    async def test_reset_missing_experiment_returns_404(
        self, client, wired_app, app_with_db
    ):
        """invariant: resetting a non-existent experiment returns 404."""
        resp = await client.post("/api/v1/experiments/does-not-exist/reset")
        assert resp.status_code == 404, resp.text


# ── scenario 12 ───────────────────────────────────────────────────────────────


CONTEXT_SCHEMA = [
    {"name": "device", "type": "categorical", "values": ["mobile", "desktop"]},
    {"name": "price", "type": "numeric", "min": 0, "max": 200},
    {"name": "returning", "type": "boolean"},
]


class TestCreateExperimentWithContextSchema:
    async def test_schema_derives_dim_and_reaches_redis(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: a declared context_schema is stored canonically, dim is derived
        from it rather than supplied, and both reach the redis record the select
        hot path reads.
        """
        pool_id = await _create_pool(client, name="ctx-schema-pool")

        data = await _create_experiment(
            client,
            pool_id,
            name="personalized-hero",
            policy="LinUCBPolicy",
            policy_params={"alpha": 1.5, "context_schema": CONTEXT_SCHEMA},
        )

        # intercept + device(2+other) + price + returning = 6
        assert data["policy_params"]["dim"] == 6
        assert data["policy_params"]["alpha"] == 1.5
        assert len(data["policy_params"]["context_schema"]) == 3

        # stored canonically: json ints become floats on the numeric bounds
        stored_price = data["policy_params"]["context_schema"][1]
        assert stored_price["min"] == 0.0
        assert stored_price["max"] == 200.0

        redis_data = await wired_app.svc._redis.get_experiment("dev-tenant", data["id"])
        assert redis_data["policy_params"]["dim"] == 6
        assert redis_data["policy_params"]["context_schema"] == (
            data["policy_params"]["context_schema"]
        )

    async def test_schema_with_explicit_dim_returns_400(
        self, client, wired_app, app_with_db
    ):
        """one source of truth: a mismatch would be silently wrong."""
        pool_id = await _create_pool(client, name="ctx-conflict-pool")

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "conflicting",
                "pool_id": pool_id,
                "policy": "LinUCBPolicy",
                "policy_params": {"context_schema": CONTEXT_SCHEMA, "dim": 6},
                "enabled": True,
            },
        )

        assert resp.status_code == 400
        assert "dim is derived" in resp.text

    async def test_over_wide_schema_returns_400_naming_the_width(
        self, client, wired_app, app_with_db
    ):
        pool_id = await _create_pool(client, name="ctx-wide-pool")

        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "too-wide",
                "pool_id": pool_id,
                "policy": "LinUCBPolicy",
                "policy_params": {
                    "context_schema": [
                        {
                            "name": "country",
                            "type": "categorical",
                            "values": [f"c{i}" for i in range(80)],
                        }
                    ]
                },
                "enabled": True,
            },
        )

        assert resp.status_code == 400
        assert "82" in resp.text

    async def test_dim_only_creation_still_works(self, client, wired_app, app_with_db):
        """the vector escape hatch is untouched."""
        pool_id = await _create_pool(client, name="ctx-dimonly-pool")

        data = await _create_experiment(
            client,
            pool_id,
            name="raw-vector",
            policy="LinUCBPolicy",
            policy_params={"dim": 4},
        )

        assert data["policy_params"]["dim"] == 4
        assert "context_schema" not in data["policy_params"]

    async def test_auto_policy_with_schema_scopes_contextual_learners(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: a schema on the auto path implies use_context, the derived dim
        is merged into every contextual learner, and the parent carries the schema
        because the select edge encodes against the parent.
        """
        pool_id = await _create_pool(client, name="ctx-auto-pool")

        data = await _create_experiment(
            client,
            pool_id,
            name="auto-contextual",
            policy="auto",
            policy_params={
                "reward_type": "binary",
                "context_schema": CONTEXT_SCHEMA,
            },
        )

        parent_params = data["policy_params"]
        assert parent_params["use_context"] is True
        assert parent_params["dim"] == 6

        stored = parent_params["context_schema"]
        assert [p["name"] for p in stored] == ["device", "price", "returning"]
        assert stored[1]["min"] == 0.0

        learner_ids = parent_params["learners"]
        assert learner_ids

        for learner_id in learner_ids:
            resp = await client.get(f"/api/v1/experiments/{learner_id}")
            assert resp.status_code == 200
            assert resp.json()["policy_params"]["dim"] == 6


# ── scenario 13 ───────────────────────────────────────────────────────────────


class TestPatchContextSchema:
    async def _create_contextual(self, client, name: str) -> dict:
        pool_id = await _create_pool(client, name=f"{name}-pool")
        return await _create_experiment(
            client,
            pool_id,
            name=name,
            policy="LinUCBPolicy",
            policy_params={"alpha": 1.5, "context_schema": CONTEXT_SCHEMA},
        )

    async def test_resending_the_same_schema_allows_tuning(
        self, client, wired_app, app_with_db
    ):
        """a schema-preserving patch is the only way to tune another param."""
        exp = await self._create_contextual(client, "patch-same")

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}",
            json={
                "policy_params": {
                    "alpha": 2.5,
                    "context_schema": exp["policy_params"]["context_schema"],
                }
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["policy_params"]["alpha"] == 2.5
        assert resp.json()["policy_params"]["dim"] == 6

    async def test_altering_the_schema_returns_409(
        self, client, wired_app, app_with_db
    ):
        exp = await self._create_contextual(client, "patch-altered")
        altered = [*CONTEXT_SCHEMA[:1], {"name": "plan", "type": "boolean"}]

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}",
            json={"policy_params": {"alpha": 1.5, "context_schema": altered}},
        )

        assert resp.status_code == 409
        assert "fixed when the experiment is created" in resp.text

    async def test_omitting_the_schema_returns_409(
        self, client, wired_app, app_with_db
    ):
        """policy_params is replaced wholesale, so omission would drop the schema."""
        exp = await self._create_contextual(client, "patch-omitted")

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}",
            json={"policy_params": {"alpha": 2.0}},
        )

        assert resp.status_code == 409
        assert "would drop it" in resp.text

    async def test_enabling_without_touching_policy_params_still_works(
        self, client, wired_app, app_with_db
    ):
        """the guard only runs when policy_params is part of the patch."""
        exp = await self._create_contextual(client, "patch-enabled")

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}", json={"enabled": False}
        )

        assert resp.status_code == 200
        assert resp.json()["enabled"] is False


# ── scenario 14 ───────────────────────────────────────────────────────────────


class TestPatchContextDim:
    """the dim-only escape hatch has no schema to protect it, so dim is guarded."""

    async def _create_vector_mode(self, client, name: str, dim: int = 4) -> dict:
        pool_id = await _create_pool(client, name=f"{name}-pool")
        return await _create_experiment(
            client,
            pool_id,
            name=name,
            policy="LinUCBPolicy",
            policy_params={"alpha": 1.5, "dim": dim},
        )

    async def test_resending_the_same_dim_allows_tuning(
        self, client, wired_app, app_with_db
    ):
        exp = await self._create_vector_mode(client, "patch-same-dim")

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}",
            json={"policy_params": {"alpha": 2.5, "dim": 4}},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["policy_params"]["alpha"] == 2.5

    async def test_widening_dim_returns_409_naming_both_widths(
        self, client, wired_app, app_with_db
    ):
        """this used to be accepted, then 500."""
        exp = await self._create_vector_mode(client, "patch-widened")

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}",
            json={"policy_params": {"alpha": 1.5, "dim": 6}},
        )

        assert resp.status_code == 409
        assert "stored width is 4" in resp.text
        assert "requested 6" in resp.text

    async def test_omitting_dim_returns_409(self, client, wired_app, app_with_db):
        exp = await self._create_vector_mode(client, "patch-dropped-dim")

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}",
            json={"policy_params": {"alpha": 2.0}},
        )

        assert resp.status_code == 409
        assert "fixed when the experiment is created" in resp.text

    async def test_non_contextual_experiment_is_unaffected(
        self, client, wired_app, app_with_db
    ):
        """no width to protect, so tuning stays open."""
        pool_id = await _create_pool(client, name="patch-no-dim-pool")
        exp = await _create_experiment(
            client,
            pool_id,
            name="patch-no-dim",
            policy="BetaTSPolicy",
            policy_params={"alpha_prior": 1.0},
        )

        resp = await client.patch(
            f"/api/v1/experiments/{exp['id']}",
            json={"policy_params": {"alpha_prior": 3.0}},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["policy_params"]["alpha_prior"] == 3.0
