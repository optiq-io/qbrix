"""the api-key and seat caps each plan tier sets, enforced by AuthService."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from svc.proxy.tests.unit.auth import test_auth_service as _core

auth_service = _core.auth_service
mock_redis_client = _core.mock_redis_client
_make_api_key_record = _core._make_api_key_record
_make_tenant_record = _core._make_tenant_record
_make_user_record = _core._make_user_record


class TestPlanCapsAPIKey:
    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_plan_limit_reached(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(plan_tier="free")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        # free plan allows 2 keys, the workspace already holds 2
        mock_key_repo = AsyncMock()
        mock_key_repo.count_by_tenant = AsyncMock(return_value=2)

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_key_repo
            ),
        ):
            with pytest.raises(ValueError, match="api key limit reached"):
                await auth_service.create_api_key("u-1")

        mock_key_repo.count_by_tenant.assert_awaited_once_with("t-1")
        mock_key_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_limit_counts_the_whole_tenant_not_the_caller(
        self, mock_get_session, auth_service
    ):
        """keys held by other members of the workspace consume the same quota."""
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(id="u-2", plan_tier="free")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        # u-2 owns no keys, but two teammates in t-1 do
        mock_key_repo = AsyncMock()
        mock_key_repo.count_by_tenant = AsyncMock(return_value=2)

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_key_repo
            ),
        ):
            with pytest.raises(ValueError, match="api key limit reached"):
                await auth_service.create_api_key("u-2")

        mock_key_repo.list_by_user.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_over_limit_tenant_keeps_its_keys(
        self, mock_get_session, auth_service
    ):
        """a workspace grandfathered above the cap loses nothing; only creation stops."""
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(plan_tier="free")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        # 2 seats x 3 keys issued under the old per-user limit
        mock_key_repo = AsyncMock()
        mock_key_repo.count_by_tenant = AsyncMock(return_value=6)

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_key_repo
            ),
        ):
            with pytest.raises(ValueError, match="api key limit reached"):
                await auth_service.create_api_key("u-1")

        mock_key_repo.deactivate.assert_not_awaited()
        mock_key_repo.delete.assert_not_awaited()
        mock_key_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_key_limit_follows_the_tenant_not_the_user_row(
        self, mock_get_session, auth_service
    ):
        """a stale users.plan_tier must not grant an unlimited key allowance."""
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        # the user row still claims growth; the tenant is what actually pays
        user = _make_user_record(plan_tier="growth")
        user.tenant = _make_tenant_record(plan_tier="free")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        mock_key_repo = AsyncMock()
        mock_key_repo.count_by_tenant = AsyncMock(return_value=2)
        mock_key_repo.create = AsyncMock(return_value=_make_api_key_record())

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_key_repo
            ),
        ):
            with pytest.raises(ValueError, match="api key limit reached for free plan"):
                await auth_service.create_api_key("u-1")

        mock_key_repo.create.assert_not_awaited()


class TestPlanCapsCreateInvite:
    _wire_repos = _core.TestAuthServiceCreateInvite._wire_repos
    _patch_repos = _core.TestAuthServiceCreateInvite._patch_repos

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.settings")
    @patch("proxysvc.mod.auth.service.secrets")
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_seat_limit_follows_the_tenant_not_the_inviter_row(
        self, mock_get_session, mock_secrets, mock_settings, auth_service
    ):
        """the inviter's stale users.plan_tier must not decide the seat limit."""
        mock_settings.console_origin = "https://cloud.qbrix.io"
        mock_secrets.token_urlsafe.return_value = "invite-token-abc"
        user_repo, invite_repo, tenant_repo = self._wire_repos(mock_get_session)
        auth_service._email = AsyncMock()

        # counts that would breach free (3 seats), on a tenant that is enterprise
        user_repo.count_by_tenant = AsyncMock(return_value=50)
        invite_repo.count_pending_by_tenant = AsyncMock(return_value=10)
        user_repo.get = AsyncMock(return_value=_make_user_record(plan_tier="free"))
        tenant_repo.get = AsyncMock(
            return_value=_make_tenant_record(name="Acme", plan_tier="enterprise")
        )

        p1, p2, p3 = self._patch_repos(user_repo, invite_repo, tenant_repo)
        with p1, p2, p3:
            await auth_service.create_invite(
                tenant_id="t-1",
                email="invitee@example.com",
                role="member",
                invited_by="u-1",
            )

        invite_repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.settings")
    @patch("proxysvc.mod.auth.service.secrets")
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_seat_limit_counts_members_and_pending_invites(
        self, mock_get_session, mock_secrets, mock_settings, auth_service
    ):
        mock_settings.console_origin = "https://cloud.qbrix.io"
        mock_secrets.token_urlsafe.return_value = "invite-token-abc"
        user_repo, invite_repo, tenant_repo = self._wire_repos(mock_get_session)
        # free plan allows 3 seats: 2 members + 1 outstanding invite fills it
        user_repo.count_by_tenant = AsyncMock(return_value=2)
        invite_repo.count_pending_by_tenant = AsyncMock(return_value=1)

        p1, p2, p3 = self._patch_repos(user_repo, invite_repo, tenant_repo)
        with p1, p2, p3:
            with pytest.raises(ValueError, match="seat limit reached"):
                await auth_service.create_invite(
                    tenant_id="t-1",
                    email="invitee@example.com",
                    role="member",
                    invited_by="u-1",
                )

        invite_repo.create.assert_not_awaited()
