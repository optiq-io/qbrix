"""tests for the per-email throttle used by the login / forgot-password routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from proxysvc.transport.http.router.auth import _throttle_email
from proxysvc.transport.http.exception import RateLimitedException


class TestThrottleEmail:

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.router.auth.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_blocks_and_lowercases_email(self, mock_op, mock_settings):
        mock_settings.runenv = "prod"
        mock_op.check_auth_endpoint_rate_limit = AsyncMock(return_value=(False, 12))

        with pytest.raises(RateLimitedException) as exc_info:
            await _throttle_email("login", "User@Example.COM", 10)

        assert exc_info.value.headers["Retry-After"] == "12"
        mock_op.check_auth_endpoint_rate_limit.assert_awaited_once_with(
            "login:email", "user@example.com", 10
        )

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.router.auth.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_allows_under_limit(self, mock_op, mock_settings):
        mock_settings.runenv = "prod"
        mock_op.check_auth_endpoint_rate_limit = AsyncMock(return_value=(True, 59))

        # should not raise
        await _throttle_email("forgot", "user@example.com", 3)

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.router.auth.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_dev_mode_bypasses(self, mock_op, mock_settings):
        mock_settings.runenv = "dev"
        mock_op.check_auth_endpoint_rate_limit = AsyncMock(return_value=(False, 30))

        await _throttle_email("login", "user@example.com", 10)

        mock_op.check_auth_endpoint_rate_limit.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.transport.http.router.auth.settings")
    @patch("proxysvc.mod.auth.operator.auth_operator")
    async def test_resend_verification_scope(self, mock_op, mock_settings):
        mock_settings.runenv = "prod"
        mock_op.check_auth_endpoint_rate_limit = AsyncMock(return_value=(True, 59))

        await _throttle_email("resend_verification", "User@Example.COM", 3)

        mock_op.check_auth_endpoint_rate_limit.assert_awaited_once_with(
            "resend_verification:email", "user@example.com", 3
        )
