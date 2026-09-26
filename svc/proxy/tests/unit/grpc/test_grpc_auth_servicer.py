"""unit tests for AuthGRPCServicer.RegisterUser tier/role clamping."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import grpc
import pytest

from qbrixproto import auth_pb2

from proxysvc.core.error import InvalidIdentityError
from proxysvc.core.error import SignupClosedError
from proxysvc.transport.grpc.auth.server import AuthGRPCServicer
from proxysvc.transport.grpc.exception.interceptor import _map_domain_error


@pytest.fixture
def auth_service():
    service = MagicMock()
    service.register_user = AsyncMock(
        return_value={
            "id": "u1",
            "email": "escalate@example.com",
            "plan_tier": "free",
            "role": "admin",
            "is_active": True,
            "created_at": 0.0,
            "updated_at": 0.0,
        }
    )
    service.update_user = AsyncMock(
        return_value={
            "id": "u1",
            "email": "escalate@example.com",
            "plan_tier": "free",
            "role": "admin",
            "is_active": False,
            "created_at": 0.0,
            "updated_at": 0.0,
        }
    )
    return service


@pytest.fixture
def servicer(auth_service):
    return AuthGRPCServicer(auth_service)


@pytest.fixture
def grpc_context():
    return MagicMock()


class TestRegisterUserClampsPrivilegedFields:
    """RegisterUser is public (see PUBLIC_METHODS), so the request must not be
    able to assign its own tier or role."""

    async def test_privileged_fields_are_not_forwarded(
        self, servicer, auth_service, grpc_context
    ):
        request = auth_pb2.RegisterUserRequest(
            email="escalate@example.com",
            password="super-secret-123",
            plan_tier=auth_pb2.PLAN_TIER_ENTERPRISE,
            role=auth_pb2.ROLE_ADMIN,
        )

        await servicer.RegisterUser(request, grpc_context)

        auth_service.register_user.assert_awaited_once()
        kwargs = auth_service.register_user.await_args.kwargs
        assert "plan_tier" not in kwargs
        assert "role" not in kwargs

    async def test_registers_user_and_maps_response(
        self, servicer, auth_service, grpc_context
    ):
        request = auth_pb2.RegisterUserRequest(
            email="escalate@example.com",
            password="super-secret-123",
        )

        response = await servicer.RegisterUser(request, grpc_context)

        assert response.user.email == "escalate@example.com"
        assert response.user.plan_tier == auth_pb2.PLAN_TIER_FREE


class TestUpdateUserRejectsPlanTier:
    """the tier belongs to the tenant, and UpdateUser is addressed by user_id,
    so the field can no longer be honoured. it must fail rather than report a
    success the caller would wrongly trust."""

    async def test_plan_tier_is_rejected(self, servicer, auth_service, grpc_context):
        request = auth_pb2.UpdateUserRequest(
            user_id="u1",
            plan_tier=auth_pb2.PLAN_TIER_ENTERPRISE,
        )

        response = await servicer.UpdateUser(request, grpc_context)

        grpc_context.set_code.assert_called_once_with(grpc.StatusCode.INVALID_ARGUMENT)
        auth_service.update_user.assert_not_awaited()
        assert not response.HasField("user")

    async def test_is_active_still_updates(self, servicer, auth_service, grpc_context):
        request = auth_pb2.UpdateUserRequest(user_id="u1", is_active=False)

        response = await servicer.UpdateUser(request, grpc_context)

        auth_service.update_user.assert_awaited_once_with("u1", is_active=False)
        assert response.user.id == "u1"


class TestRegisterUserHonoursTheSignupMode:
    """the signup mode is enforced in AuthService, so grpc gets it for free —
    but only if the servicer lets the error reach the exception interceptor
    instead of swallowing it as an internal error."""

    async def test_signup_closed_propagates_to_the_interceptor(
        self, servicer, auth_service, grpc_context
    ):
        auth_service.register_user = AsyncMock(
            side_effect=SignupClosedError("public registration is closed")
        )
        request = auth_pb2.RegisterUserRequest(
            email="stranger@example.com", password="super-secret-123"
        )

        with pytest.raises(SignupClosedError):
            await servicer.RegisterUser(request, grpc_context)

        grpc_context.set_code.assert_not_called()

    def test_the_interceptor_maps_it_to_permission_denied(self):
        mapped = _map_domain_error(SignupClosedError("closed"))

        assert mapped.status_code == grpc.StatusCode.PERMISSION_DENIED


class TestRegisterUserRefusesInvalidIdentity:
    async def test_the_error_propagates_to_the_interceptor(
        self, servicer, auth_service, grpc_context
    ):
        auth_service.register_user = AsyncMock(
            side_effect=InvalidIdentityError("name must not contain a link")
        )
        request = auth_pb2.RegisterUserRequest(
            email="bot@example.com", password="super-secret-123"
        )

        with pytest.raises(InvalidIdentityError):
            await servicer.RegisterUser(request, grpc_context)

        grpc_context.set_code.assert_not_called()

    def test_the_interceptor_maps_it_to_invalid_argument(self):
        mapped = _map_domain_error(InvalidIdentityError("name must not contain a link"))

        assert mapped.status_code == grpc.StatusCode.INVALID_ARGUMENT
        assert mapped.detail == "name must not contain a link"
