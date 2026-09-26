"""http integration tests for auth router with real auth (non-dev mode).

invariants verified:
  scenario 1: register → login → access token works on GET /api/auth/profile
  scenario 2: refresh token issues a new access token that works
  scenario 3: api key lifecycle: create → use → delete → 401
  scenario 4: api key rotation: rotate → old key 401, new key 200
  scenario 5: member role → 403 on PATCH /api/auth/workspace (require_admin_user)

role defaults (confirmed from auth/service.py register_user()):
  - when no tenant_id is provided, a new tenant is auto-created and the
    registering user's role is forced to "admin" regardless of the role field
  - second users can only be "member" role via the invite → accept_invite flow
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient

import proxysvc.config as _config_module
import proxysvc.mod.auth.operator as _op_module


@pytest_asyncio.fixture
async def auth_client(wired_app, monkeypatch) -> AsyncGenerator[AsyncClient, Any]:
    """async httpx client in non-dev mode, so the middleware runs the real auth path."""
    monkeypatch.setattr(_config_module.settings, "runenv", "test")

    transport = ASGITransport(app=wired_app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── helpers ───────────────────────────────────────────────────────────────────


async def _verify_email_for_user(user_id: str) -> None:
    """consume the verification token issued at registration so the user can log
    in. non-dev mode does not auto-verify, so this mirrors the real onboarding
    step (clicking the emailed link) by reading the token straight from redis."""
    redis = _op_module.auth_operator._service._redis.client
    for key in await redis.keys("qbrix:email_verify:*"):
        if await redis.get(key) == user_id:
            token = key.removeprefix("qbrix:email_verify:")
            await _op_module.auth_operator.verify_email(token)
            return


async def _verification_token_for_user(user_id: str) -> str | None:
    """return the pending verification token for a user, read from redis."""
    redis = _op_module.auth_operator._service._redis.client
    for key in await redis.keys("qbrix:email_verify:*"):
        if await redis.get(key) == user_id:
            return key.removeprefix("qbrix:email_verify:")
    return None


async def _set_tenant_tier_for_user(user_id: str, tier: str) -> None:
    """promote a user's tenant the way billing reconciliation does — the tenant
    owns the tier, and both caches holding it have to be dropped."""
    from qbrixstore.postgres.session import get_session

    from proxysvc.mod.auth.repository import TenantRepository

    service = _op_module.auth_operator._service
    user = await service.get_user(user_id)
    tenant_id = user["tenant_id"]

    async with get_session() as session:
        await TenantRepository(session).update_plan_tier(tenant_id, tier)

    service.invalidate_tenant(tenant_id)
    service.entitlements.invalidate(tenant_id)


async def _register_and_login(
    client: AsyncClient,
    email: str,
    password: str,
    name: str | None = None,
) -> dict:
    """register a user, verify their email, and return the LoginResponse dict."""
    reg = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": name},
    )
    if reg.status_code == 201:
        await _verify_email_for_user(reg.json()["id"])
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return resp.json()


# ── scenario 1: register → login → profile ────────────────────────────────────


class TestRegisterLoginProfile:
    async def test_register_returns_201_with_user_shape(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: POST /api/auth/register creates a user and returns 201 with
        the UserResponse shape (id, email, role, plan_tier, is_active, created_at).
        """
        body = {
            "email": "alice@example.com",
            "password": "super-secret-123",
            "name": "Alice",
        }

        response = await auth_client.post("/api/auth/register", json=body)

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "alice@example.com"
        assert data["name"] == "Alice"
        assert "id" in data
        assert "role" in data
        assert data["is_active"] is True
        # founding user (no tenant_id provided) is forced to admin
        assert data["role"] == "admin"
        # a freshly registered user is unverified until they confirm their email
        assert data["email_verified"] is False

    async def test_register_ignores_self_assigned_plan_tier(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: a plan_tier in the register body never reaches the user
        record. register is unauthenticated, so a self-declared paid tier would
        unlock EE features and bypass the free cap with no subscription behind
        it.
        """
        response = await auth_client.post(
            "/api/auth/register",
            json={
                "email": "escalate@example.com",
                "password": "super-secret-123",
                "plan_tier": "enterprise",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["plan_tier"] == ("free" if data["edition"] == "cloud" else None)

    async def test_register_ignores_self_assigned_role(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: a role in the register body is ignored. the founding user is
        admin because it founds a tenant, not because it asked.
        """
        response = await auth_client.post(
            "/api/auth/register",
            json={
                "email": "viewer-who-asked@example.com",
                "password": "super-secret-123",
                "role": "viewer",
            },
        )

        assert response.status_code == 201
        assert response.json()["role"] == "admin"

    async def test_login_returns_access_and_refresh_tokens(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: POST /api/auth/login returns both access_token and refresh_token
        along with the user payload. token_type must be "bearer".
        """
        reg = await auth_client.post(
            "/api/auth/register",
            json={"email": "bob@example.com", "password": "pass-word-456"},
        )
        await _verify_email_for_user(reg.json()["id"])

        response = await auth_client.post(
            "/api/auth/login",
            json={"email": "bob@example.com", "password": "pass-word-456"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "bob@example.com"
        assert data["user"]["email_verified"] is True

    async def test_access_token_grants_profile_access(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: the access_token from /login is accepted by the middleware and
        GET /api/auth/profile returns the authenticated user's data.

        end-to-end JWT path: register → login → use access token → profile.
        """
        login_data = await _register_and_login(
            auth_client,
            email="carol@example.com",
            password="carol-pw-789",
            name="Carol",
        )

        access_token = login_data["access_token"]

        response = await auth_client.get(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        profile = response.json()
        assert profile["email"] == "carol@example.com"
        assert profile["name"] == "Carol"
        assert profile["is_active"] is True
        assert profile["plan_tier"] == (
            "free" if profile["edition"] == "cloud" else None
        )
        # a founding user alone in a fresh tenant: one seat, nothing else used
        assert profile["usage"]["api_keys"] == 0
        assert profile["usage"]["seats"] == 1
        assert profile["usage"]["active_experiments"] == 0

    async def test_usage_api_keys_counts_the_whole_workspace(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: usage.api_keys is tenant-wide while GET /auth/api-keys stays
        caller-only.

        two members of one tenant, one key each: the per-user list returns 1 and
        usage.api_keys returns 2.
        """
        admin_login = await _register_and_login(
            auth_client,
            email="owner@example.com",
            password="owner-pw-123",
            name="Owner",
        )
        admin_header = {"Authorization": f"Bearer {admin_login['access_token']}"}

        invite = await auth_client.post(
            "/api/auth/workspace/invites",
            json={"email": "colleague@example.com", "role": "member"},
            headers=admin_header,
        )
        assert invite.status_code == 201, invite.text

        accept = await auth_client.post(
            f"/api/auth/invites/{invite.json()['token']}/accept",
            json={"name": "Colleague", "password": "colleague-pw-1"},
        )
        assert accept.status_code == 201, accept.text

        member_login = await auth_client.post(
            "/api/auth/login",
            json={"email": "colleague@example.com", "password": "colleague-pw-1"},
        )
        assert member_login.status_code == 200, member_login.text
        member_header = {
            "Authorization": f"Bearer {member_login.json()['access_token']}"
        }

        for header in (admin_header, member_header):
            created = await auth_client.post(
                "/api/auth/api-keys", json={"name": "key"}, headers=header
            )
            assert created.status_code == 201, created.text

        for header in (admin_header, member_header):
            listed = await auth_client.get("/api/auth/api-keys", headers=header)
            assert listed.status_code == 200
            assert len(listed.json()) == 1

            profile = await auth_client.get("/api/auth/profile", headers=header)
            assert profile.status_code == 200
            usage = profile.json()["usage"]
            assert usage["api_keys"] == 2
            assert usage["seats"] == 2

    async def test_profile_without_token_returns_401(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: GET /api/auth/profile without auth → 401 (middleware rejects
        before the route runs).
        """
        response = await auth_client.get("/api/auth/profile")

        assert response.status_code == 401


# ── scenario 2: refresh token → new access token works ───────────────────────


class TestRefreshToken:
    async def test_refresh_returns_new_access_token(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: POST /api/auth/refresh with a valid refresh token returns a
        new access_token (token_type "bearer"). the response schema is
        RefreshTokenResponse: {access_token, token_type}.
        """
        login_data = await _register_and_login(
            auth_client,
            email="dave@example.com",
            password="dave-pass-111",
        )

        refresh_token = login_data["refresh_token"]

        response = await auth_client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_new_access_token_from_refresh_works_on_profile(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: the access_token issued by /refresh is a valid JWT accepted
        by the middleware. GET /api/auth/profile with the new token → 200.

        this verifies the full refresh rotation path produces a usable credential.
        """
        login_data = await _register_and_login(
            auth_client,
            email="eve@example.com",
            password="eve-pass-222",
            name="Eve",
        )

        refresh_response = await auth_client.post(
            "/api/auth/refresh",
            json={"refresh_token": login_data["refresh_token"]},
        )
        assert refresh_response.status_code == 200
        new_access_token = refresh_response.json()["access_token"]

        profile_response = await auth_client.get(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {new_access_token}"},
        )

        assert profile_response.status_code == 200
        assert profile_response.json()["email"] == "eve@example.com"

    async def test_invalid_refresh_token_returns_401(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: /api/auth/refresh with a bogus token → 401 (InvalidTokenException).
        the route, not the middleware, handles this: /api/auth/refresh is a public path.
        """
        response = await auth_client.post(
            "/api/auth/refresh",
            json={"refresh_token": "not-a-valid-refresh-token"},
        )

        assert response.status_code == 401


# ── scenario 3: api key lifecycle ────────────────────────────────────────────


class TestAPIKeyLifecycle:
    async def test_create_api_key_returns_201_with_optiq_prefix(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: POST /api/auth/api-keys returns 201 and the raw key value
        starts with the "optiq_" prefix defined in AuthService._api_key_prefix.
        """
        login_data = await _register_and_login(
            auth_client,
            email="frank@example.com",
            password="frank-pw-333",
        )
        access_token = login_data["access_token"]

        response = await auth_client.post(
            "/api/auth/api-keys",
            json={"name": "test-key"},
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["key"].startswith("optiq_")
        assert data["name"] == "test-key"
        assert data["is_active"] is True

    async def test_active_api_key_authenticates_protected_endpoint(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: a freshly created api key (via X-API-Key header) is accepted
        by the middleware and GET /api/v1/pools returns 200.
        """
        login_data = await _register_and_login(
            auth_client,
            email="grace@example.com",
            password="grace-pw-444",
        )
        access_token = login_data["access_token"]

        key_response = await auth_client.post(
            "/api/auth/api-keys",
            json={"name": "pools-key"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert key_response.status_code == 201
        raw_key = key_response.json()["key"]

        pools_response = await auth_client.get(
            "/api/v1/pools",
            headers={"X-API-Key": raw_key},
        )

        assert pools_response.status_code == 200

    async def test_deleted_api_key_returns_401_on_subsequent_use(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: after DELETE /api/auth/api-keys/{id}, the deactivated key is
        rejected by the middleware with 401 on subsequent protected endpoint calls.

        lifecycle: create → use (200) → delete → use again (401).
        """
        login_data = await _register_and_login(
            auth_client,
            email="hank@example.com",
            password="hank-pw-555",
        )
        access_token = login_data["access_token"]
        auth_header = {"Authorization": f"Bearer {access_token}"}

        key_response = await auth_client.post(
            "/api/auth/api-keys",
            json={"name": "lifecycle-key"},
            headers=auth_header,
        )
        assert key_response.status_code == 201
        key_data = key_response.json()
        raw_key = key_data["key"]
        key_id = key_data["id"]

        # confirm the key works before deletion
        pre_delete = await auth_client.get(
            "/api/v1/pools",
            headers={"X-API-Key": raw_key},
        )
        assert pre_delete.status_code == 200

        # delete the key
        delete_response = await auth_client.delete(
            f"/api/auth/api-keys/{key_id}",
            headers=auth_header,
        )
        assert delete_response.status_code == 200

        # use deactivated key → must be rejected
        post_delete = await auth_client.get(
            "/api/v1/pools",
            headers={"X-API-Key": raw_key},
        )
        assert post_delete.status_code == 401


# ── scenario 4: api key rotation ─────────────────────────────────────────────


class TestAPIKeyRotation:
    async def test_rotation_returns_new_key_with_optiq_prefix(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: POST /api/auth/api-keys/{id}/rotate returns 200 with a new
        raw key (starts with "optiq_") and the same key id.
        """
        login_data = await _register_and_login(
            auth_client,
            email="iris@example.com",
            password="iris-pw-666",
        )
        access_token = login_data["access_token"]
        auth_header = {"Authorization": f"Bearer {access_token}"}

        key_response = await auth_client.post(
            "/api/auth/api-keys",
            json={"name": "rotate-me"},
            headers=auth_header,
        )
        assert key_response.status_code == 201
        key_id = key_response.json()["id"]

        rotate_response = await auth_client.post(
            f"/api/auth/api-keys/{key_id}/rotate",
            headers=auth_header,
        )

        assert rotate_response.status_code == 200
        rotated = rotate_response.json()
        assert rotated["id"] == key_id
        assert rotated["key"].startswith("optiq_")
        assert rotated["key"] != key_response.json()["key"]

    async def test_old_key_rejected_after_rotation(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: after rotation, the original key is no longer valid.
        GET /api/v1/pools with old key → 401.
        """
        login_data = await _register_and_login(
            auth_client,
            email="jake@example.com",
            password="jake-pw-777",
        )
        access_token = login_data["access_token"]
        auth_header = {"Authorization": f"Bearer {access_token}"}

        key_response = await auth_client.post(
            "/api/auth/api-keys",
            json={"name": "rotate-old"},
            headers=auth_header,
        )
        assert key_response.status_code == 201
        old_key = key_response.json()["key"]
        key_id = key_response.json()["id"]

        # confirm old key works before rotation
        pre_rotate = await auth_client.get(
            "/api/v1/pools",
            headers={"X-API-Key": old_key},
        )
        assert pre_rotate.status_code == 200

        # rotate the key
        rotate_response = await auth_client.post(
            f"/api/auth/api-keys/{key_id}/rotate",
            headers=auth_header,
        )
        assert rotate_response.status_code == 200

        # old key must now be rejected
        post_rotate_old = await auth_client.get(
            "/api/v1/pools",
            headers={"X-API-Key": old_key},
        )
        assert post_rotate_old.status_code == 401

    async def test_new_key_works_after_rotation(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: the new key issued by rotation is accepted by the middleware.
        GET /api/v1/pools with new key → 200.
        """
        login_data = await _register_and_login(
            auth_client,
            email="kate@example.com",
            password="kate-pw-888",
        )
        access_token = login_data["access_token"]
        auth_header = {"Authorization": f"Bearer {access_token}"}

        key_response = await auth_client.post(
            "/api/auth/api-keys",
            json={"name": "rotate-new"},
            headers=auth_header,
        )
        assert key_response.status_code == 201
        key_id = key_response.json()["id"]

        rotate_response = await auth_client.post(
            f"/api/auth/api-keys/{key_id}/rotate",
            headers=auth_header,
        )
        assert rotate_response.status_code == 200
        new_key = rotate_response.json()["key"]

        post_rotate_new = await auth_client.get(
            "/api/v1/pools",
            headers={"X-API-Key": new_key},
        )

        assert post_rotate_new.status_code == 200


# ── scenario 5: member role → 403 on PATCH /api/auth/workspace ───────────────


class TestAdminOnlyEndpoint:
    async def test_member_role_blocked_from_workspace_update(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: require_admin_user rejects a "member" role user with 403.

        role acquisition path:
          1. admin registers → becomes admin (founding user rule in register_user)
          2. admin creates an invite for member@example.com with role="member"
          3. member accepts the invite via POST /api/auth/invites/{token}/accept
          4. member logs in and attempts PATCH /api/auth/workspace → 403

        this is the only public-API path to obtain a "member" role without
        touching the db directly, because register_user always forces "admin"
        for new tenants.
        """
        # step 1: register the founding admin
        admin_login = await _register_and_login(
            auth_client,
            email="admin@example.com",
            password="admin-pw-999",
            name="Admin",
        )
        admin_token = admin_login["access_token"]
        admin_header = {"Authorization": f"Bearer {admin_token}"}

        # step 2: admin creates an invite for the member
        invite_response = await auth_client.post(
            "/api/auth/workspace/invites",
            json={"email": "member@example.com", "role": "member"},
            headers=admin_header,
        )
        assert invite_response.status_code == 201, invite_response.text
        invite_token = invite_response.json()["token"]

        # step 3: member accepts invite (public endpoint, no auth required)
        accept_response = await auth_client.post(
            f"/api/auth/invites/{invite_token}/accept",
            json={"name": "Member User", "password": "member-pw-000"},
        )
        assert accept_response.status_code == 201, accept_response.text
        assert accept_response.json()["role"] == "member"

        # step 4: member logs in and gets an access token
        member_login_response = await auth_client.post(
            "/api/auth/login",
            json={"email": "member@example.com", "password": "member-pw-000"},
        )
        assert member_login_response.status_code == 200
        member_token = member_login_response.json()["access_token"]

        # step 5: member attempts PATCH /api/auth/workspace → must be 403
        patch_response = await auth_client.patch(
            "/api/auth/workspace",
            json={"name": "Hijacked Workspace"},
            headers={"Authorization": f"Bearer {member_token}"},
        )

        assert patch_response.status_code == 403
        body = patch_response.json()
        assert "detail" in body

    async def test_admin_role_allowed_on_workspace_update(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: require_admin_user passes for a user with role="admin".
        PATCH /api/auth/workspace by admin → 200.

        this is the positive-case counterpart to the member-403 test above.
        """
        admin_login = await _register_and_login(
            auth_client,
            email="admin2@example.com",
            password="admin2-pw-aaa",
            name="Admin Two",
        )
        admin_token = admin_login["access_token"]

        patch_response = await auth_client.patch(
            "/api/auth/workspace",
            json={"name": "Updated Workspace"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert patch_response.status_code == 200
        body = patch_response.json()
        assert body["name"] == "Updated Workspace"


# ── scenario 6: email verification ─────────────────────────────────────────────


class TestEmailVerification:
    async def test_login_blocked_until_verified(
        self, auth_client: AsyncClient, app_with_db
    ):
        """
        invariant: a freshly registered user cannot log in until verified; the
        block returns a distinct, machine-readable EMAIL_NOT_VERIFIED error
        rather than the generic bad-credentials message.
        """
        reg = await auth_client.post(
            "/api/auth/register",
            json={"email": "carol@example.com", "password": "carol-pw-123"},
        )
        assert reg.status_code == 201

        blocked = await auth_client.post(
            "/api/auth/login",
            json={"email": "carol@example.com", "password": "carol-pw-123"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "EMAIL_NOT_VERIFIED"

        token = await _verification_token_for_user(reg.json()["id"])
        assert token is not None
        verify = await auth_client.post("/api/auth/verify-email", json={"token": token})
        assert verify.status_code == 200

        ok = await auth_client.post(
            "/api/auth/login",
            json={"email": "carol@example.com", "password": "carol-pw-123"},
        )
        assert ok.status_code == 200
        assert ok.json()["user"]["email_verified"] is True

    async def test_verify_token_is_single_use(
        self, auth_client: AsyncClient, app_with_db
    ):
        """invariant: a verification token works once, then is rejected."""
        reg = await auth_client.post(
            "/api/auth/register",
            json={"email": "dave@example.com", "password": "dave-pw-123"},
        )
        token = await _verification_token_for_user(reg.json()["id"])

        first = await auth_client.post("/api/auth/verify-email", json={"token": token})
        assert first.status_code == 200

        second = await auth_client.post("/api/auth/verify-email", json={"token": token})
        assert second.status_code == 400

    async def test_verify_invalid_token_returns_400(
        self, auth_client: AsyncClient, app_with_db
    ):
        """invariant: an unknown/expired token is rejected with a clear 400."""
        resp = await auth_client.post(
            "/api/auth/verify-email", json={"token": "not-a-real-token"}
        )
        assert resp.status_code == 400

    async def test_resend_is_enumeration_safe_for_unknown_email(
        self, auth_client: AsyncClient, app_with_db
    ):
        """invariant: resend always returns 200, even for unknown emails."""
        resp = await auth_client.post(
            "/api/auth/resend-verification", json={"email": "nobody@example.com"}
        )
        assert resp.status_code == 200

    async def test_resend_reissues_token_for_unverified_user(
        self, auth_client: AsyncClient, app_with_db
    ):
        """invariant: resend re-issues a usable verification token."""
        reg = await auth_client.post(
            "/api/auth/register",
            json={"email": "erin@example.com", "password": "erin-pw-123"},
        )

        resp = await auth_client.post(
            "/api/auth/resend-verification", json={"email": "erin@example.com"}
        )
        assert resp.status_code == 200

        token = await _verification_token_for_user(reg.json()["id"])
        assert token is not None
        verify = await auth_client.post("/api/auth/verify-email", json={"token": token})
        assert verify.status_code == 200

    async def test_resend_is_noop_for_already_verified_user(
        self, auth_client: AsyncClient, app_with_db
    ):
        """invariant: resend does nothing for an already-verified account."""
        reg = await auth_client.post(
            "/api/auth/register",
            json={"email": "frank@example.com", "password": "frank-pw-123"},
        )
        await _verify_email_for_user(reg.json()["id"])

        resp = await auth_client.post(
            "/api/auth/resend-verification", json={"email": "frank@example.com"}
        )
        assert resp.status_code == 200
        # no new token issued for a verified user
        assert await _verification_token_for_user(reg.json()["id"]) is None

    async def test_invite_accepted_user_is_pre_verified(
        self, auth_client: AsyncClient, app_with_db
    ):
        """invariant: invite-accepted users are verified and log in immediately."""
        admin_login = await _register_and_login(
            auth_client,
            email="ivan@example.com",
            password="ivan-pw-123",
            name="Ivan",
        )
        admin_header = {"Authorization": f"Bearer {admin_login['access_token']}"}

        invite = await auth_client.post(
            "/api/auth/workspace/invites",
            json={"email": "wendy@example.com", "role": "member"},
            headers=admin_header,
        )
        assert invite.status_code == 201, invite.text
        invite_token = invite.json()["token"]

        accept = await auth_client.post(
            f"/api/auth/invites/{invite_token}/accept",
            json={"name": "Wendy", "password": "wendy-pw-123"},
        )
        assert accept.status_code == 201
        assert accept.json()["email_verified"] is True

        login = await auth_client.post(
            "/api/auth/login",
            json={"email": "wendy@example.com", "password": "wendy-pw-123"},
        )
        assert login.status_code == 200
