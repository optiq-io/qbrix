"""the free tier's active-experiment cap, over http.

scenario 1: POST when the plan limit is reached → 409 ExperimentLimitException
scenario 2: PATCH enabling an experiment at the plan limit → 409 ExperimentLimitException
"""

from __future__ import annotations


class TestPlanLimitOnCreate:
    async def test_create_experiment_at_plan_limit_returns_409(
        self, client, wired_app, app_with_db, tenant_a
    ):
        """
        invariant: when the active experiment count equals the plan limit, attempting
        to create one more raises ExperimentLimitException → HTTP 409.

        the free plan allows max_active_experiments=3.  we use as_tenant with
        plan_tier="free" (overriding the dev user's enterprise default) by using
        a custom _FakeUser subclass approach via as_tenant — but as_tenant always
        sets plan_tier="enterprise".  instead we override the dependency directly
        on the app to inject a free-tier user, seed 3 enabled experiments, then
        attempt a 4th.

        bug note: as_tenant hardcodes plan_tier="enterprise" so it can't model
        plan-limit tests through that fixture.  we patch get_current_user directly
        to return a free-tier user.
        """
        from proxysvc.transport.http.auth.dependencies import get_current_user
        from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
        from proxysvc.transport.http.auth.dependencies import get_current_user_id

        class _FreeTierUser:
            id = "free-user"
            tenant_id = tenant_a.id
            role = "admin"
            plan_tier = "free"
            is_active = True

        async def _free_user():
            return _FreeTierUser()

        async def _free_tenant():
            return tenant_a.id

        async def _free_user_id():
            return "free-user"

        wired_app.app.dependency_overrides[get_current_user] = _free_user
        wired_app.app.dependency_overrides[get_current_tenant_id] = _free_tenant
        wired_app.app.dependency_overrides[get_current_user_id] = _free_user_id

        try:
            pool_resp = await client.post(
                "/api/v1/pools",
                json={
                    "name": "limit-test-pool",
                    "arms": [
                        {"name": "ctrl", "metadata": {}},
                        {"name": "var", "metadata": {}},
                    ],
                },
            )
            assert pool_resp.status_code == 201, pool_resp.text
            pool_id = pool_resp.json()["id"]

            # seed 3 enabled experiments (free limit = 3)
            for i in range(3):
                r = await client.post(
                    "/api/v1/experiments",
                    json={
                        "name": f"seed-exp-{i}",
                        "pool_id": pool_id,
                        "policy": "BetaTSPolicy",
                        "policy_params": {},
                        "enabled": True,
                    },
                )
                assert r.status_code == 201, f"seed experiment {i} failed: {r.text}"

            # 4th attempt must fail
            over_limit_resp = await client.post(
                "/api/v1/experiments",
                json={
                    "name": "over-limit-exp",
                    "pool_id": pool_id,
                    "policy": "BetaTSPolicy",
                    "policy_params": {},
                    "enabled": True,
                },
            )

            # ExperimentLimitException extends ConflictException → 409
            assert (
                over_limit_resp.status_code == 409
            ), f"expected 409 at plan limit, got {over_limit_resp.status_code}: {over_limit_resp.text}"
        finally:
            wired_app.app.dependency_overrides.pop(get_current_user, None)
            wired_app.app.dependency_overrides.pop(get_current_tenant_id, None)
            wired_app.app.dependency_overrides.pop(get_current_user_id, None)


class TestPlanLimitOnPatch:
    async def test_enable_experiment_at_plan_limit_returns_409(
        self, client, wired_app, app_with_db, tenant_a
    ):
        """
        invariant: PATCH /experiments/{id} to enable=True when already at the
        plan limit raises ExperimentLimitException → HTTP 409.

        setup: create 3 enabled + 1 disabled experiment as a free-tier user.
        patch the disabled one to enabled=True → must be rejected.
        """
        from proxysvc.transport.http.auth.dependencies import get_current_user
        from proxysvc.transport.http.auth.dependencies import get_current_tenant_id
        from proxysvc.transport.http.auth.dependencies import get_current_user_id

        class _FreeTierUser:
            id = "free-user-patch"
            tenant_id = tenant_a.id
            role = "admin"
            plan_tier = "free"
            is_active = True

        async def _free_user():
            return _FreeTierUser()

        async def _free_tenant():
            return tenant_a.id

        async def _free_user_id():
            return "free-user-patch"

        wired_app.app.dependency_overrides[get_current_user] = _free_user
        wired_app.app.dependency_overrides[get_current_tenant_id] = _free_tenant
        wired_app.app.dependency_overrides[get_current_user_id] = _free_user_id

        try:
            pool_resp = await client.post(
                "/api/v1/pools",
                json={
                    "name": "patch-limit-pool",
                    "arms": [
                        {"name": "ctrl", "metadata": {}},
                        {"name": "var", "metadata": {}},
                    ],
                },
            )
            assert pool_resp.status_code == 201, pool_resp.text
            pool_id = pool_resp.json()["id"]

            # seed 3 enabled experiments to reach the limit
            for i in range(3):
                r = await client.post(
                    "/api/v1/experiments",
                    json={
                        "name": f"enabled-exp-{i}",
                        "pool_id": pool_id,
                        "policy": "BetaTSPolicy",
                        "policy_params": {},
                        "enabled": True,
                    },
                )
                assert r.status_code == 201, f"seed experiment {i} failed: {r.text}"

            # create a disabled experiment (this should succeed: plan check skips disabled)
            disabled_resp = await client.post(
                "/api/v1/experiments",
                json={
                    "name": "disabled-exp",
                    "pool_id": pool_id,
                    "policy": "BetaTSPolicy",
                    "policy_params": {},
                    "enabled": False,
                },
            )
            assert disabled_resp.status_code == 201, disabled_resp.text
            disabled_id = disabled_resp.json()["id"]

            # attempt to enable it — must be rejected at limit
            patch_resp = await client.patch(
                f"/api/v1/experiments/{disabled_id}",
                json={"enabled": True},
            )

            # ExperimentLimitError → ExperimentLimitException → 409
            assert (
                patch_resp.status_code == 409
            ), f"expected 409 when enabling at plan limit, got {patch_resp.status_code}: {patch_resp.text}"
        finally:
            wired_app.app.dependency_overrides.pop(get_current_user, None)
            wired_app.app.dependency_overrides.pop(get_current_tenant_id, None)
            wired_app.app.dependency_overrides.pop(get_current_user_id, None)
