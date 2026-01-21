from __future__ import annotations

import grpc

from qbrixproto import auth_pb2
from qbrixproto import auth_pb2_grpc

from proxysvc.http.auth.service import AuthService

PLAN_TIER_MAP = {
    auth_pb2.PLAN_TIER_FREE: "free",
    auth_pb2.PLAN_TIER_PRO: "pro",
    auth_pb2.PLAN_TIER_ENTERPRISE: "enterprise",
}

PLAN_TIER_REVERSE = {v: k for k, v in PLAN_TIER_MAP.items()}

ROLE_MAP = {
    auth_pb2.ROLE_ADMIN: "admin",
    auth_pb2.ROLE_MEMBER: "member",
    auth_pb2.ROLE_VIEWER: "viewer",
}

ROLE_REVERSE = {v: k for k, v in ROLE_MAP.items()}


class AuthGRPCServicer(auth_pb2_grpc.AuthServiceServicer):
    """grpc servicer that wraps AuthService."""

    def __init__(self, service: AuthService):
        self._service = service

    # user management

    async def RegisterUser(self, request, context):
        try:
            plan_tier = PLAN_TIER_MAP.get(request.plan_tier, "free")
            role = ROLE_MAP.get(request.role, "member")

            user_dict = await self._service.register_user(
                email=request.email,
                password=request.password,
                plan_tier=plan_tier,
                role=role,
            )
            return auth_pb2.RegisterUserResponse(user=self._dict_to_user(user_dict))
        except ValueError as e:
            context.set_code(grpc.StatusCode.ALREADY_EXISTS)
            context.set_details(str(e))
            return auth_pb2.RegisterUserResponse()
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.RegisterUserResponse()

    async def AuthenticateUser(self, request, context):
        try:
            user_dict = await self._service.authenticate_user(
                email=request.email,
                password=request.password,
            )
            if user_dict is None:
                return auth_pb2.AuthenticateUserResponse(authenticated=False)
            return auth_pb2.AuthenticateUserResponse(
                authenticated=True,
                user=self._dict_to_user(user_dict),
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.AuthenticateUserResponse(authenticated=False)

    async def GetUser(self, request, context):
        try:
            user_dict = await self._service.get_user(request.user_id)
            if user_dict is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"user not found: {request.user_id}")
                return auth_pb2.GetUserResponse()
            return auth_pb2.GetUserResponse(user=self._dict_to_user(user_dict))
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.GetUserResponse()

    async def GetUserByEmail(self, request, context):
        try:
            user_dict = await self._service.get_user_by_email(request.email)
            if user_dict is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"user not found: {request.email}")
                return auth_pb2.GetUserByEmailResponse()
            return auth_pb2.GetUserByEmailResponse(user=self._dict_to_user(user_dict))
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.GetUserByEmailResponse()

    async def UpdateUser(self, request, context):
        try:
            kwargs = {}
            if request.HasField("plan_tier"):
                kwargs["plan_tier"] = PLAN_TIER_MAP.get(request.plan_tier, "free")
            if request.HasField("is_active"):
                kwargs["is_active"] = request.is_active

            user_dict = await self._service.update_user(request.user_id, **kwargs)
            if user_dict is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"user not found: {request.user_id}")
                return auth_pb2.UpdateUserResponse()
            return auth_pb2.UpdateUserResponse(user=self._dict_to_user(user_dict))
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.UpdateUserResponse()

    async def DeactivateUser(self, request, context):
        try:
            success = await self._service.deactivate_user(request.user_id)
            return auth_pb2.DeactivateUserResponse(success=success)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.DeactivateUserResponse(success=False)

    async def AssignRole(self, request, context):
        try:
            role = ROLE_MAP.get(request.role, "member")
            user_dict = await self._service.assign_role(request.user_id, role)
            if user_dict is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"user not found: {request.user_id}")
                return auth_pb2.AssignRoleResponse(success=False)
            return auth_pb2.AssignRoleResponse(
                success=True,
                user=self._dict_to_user(user_dict),
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.AssignRoleResponse(success=False)

    # api key management

    async def CreateAPIKey(self, request, context):
        try:
            scopes = list(request.scopes) if request.scopes else None
            api_key_dict, plain_key = await self._service.create_api_key(
                user_id=request.user_id,
                name=request.name or "Default API Key",
                scopes=scopes,
            )
            return auth_pb2.CreateAPIKeyResponse(
                api_key=self._dict_to_api_key(api_key_dict),
                plain_key=plain_key,
            )
        except ValueError as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(e))
            return auth_pb2.CreateAPIKeyResponse()
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.CreateAPIKeyResponse()

    async def GetAPIKey(self, request, context):
        try:
            api_key_dict = await self._service.get_api_key(request.api_key_id)
            if api_key_dict is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"api key not found: {request.api_key_id}")
                return auth_pb2.GetAPIKeyResponse()
            return auth_pb2.GetAPIKeyResponse(
                api_key=self._dict_to_api_key(api_key_dict)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.GetAPIKeyResponse()

    async def ValidateAPIKey(self, request, context):
        try:
            api_key_dict = await self._service.validate_api_key(request.plain_key)
            if api_key_dict is None:
                return auth_pb2.ValidateAPIKeyResponse(valid=False)
            return auth_pb2.ValidateAPIKeyResponse(
                valid=True,
                api_key=self._dict_to_api_key(api_key_dict),
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.ValidateAPIKeyResponse(valid=False)

    async def ListUserAPIKeys(self, request, context):
        try:
            api_keys = await self._service.list_user_api_keys(request.user_id)
            return auth_pb2.ListUserAPIKeysResponse(
                api_keys=[self._dict_to_api_key(k) for k in api_keys]
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.ListUserAPIKeysResponse()

    async def DeactivateAPIKey(self, request, context):
        try:
            success = await self._service.deactivate_api_key(
                request.api_key_id, request.user_id
            )
            return auth_pb2.DeactivateAPIKeyResponse(success=success)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.DeactivateAPIKeyResponse(success=False)

    async def GetAPIKeyUsage(self, request, context):
        try:
            usage = await self._service.get_api_key_usage(request.api_key_id)
            return auth_pb2.GetAPIKeyUsageResponse(
                current_minute_usage=usage["current_minute_usage"],
                rate_limit_per_minute=usage["rate_limit_per_minute"],
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.GetAPIKeyUsageResponse()

    # rate limiting

    async def CheckRateLimit(self, request, context):
        try:
            allowed, remaining, limit = await self._service.check_rate_limit(
                request.api_key_id
            )
            return auth_pb2.CheckRateLimitResponse(
                allowed=allowed,
                remaining=remaining,
                limit=limit,
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.CheckRateLimitResponse(allowed=False)

    async def CheckUserRateLimit(self, request, context):
        try:
            allowed, remaining, limit = await self._service.check_user_rate_limit(
                request.user_id
            )
            return auth_pb2.CheckUserRateLimitResponse(
                allowed=allowed,
                remaining=remaining,
                limit=limit,
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.CheckUserRateLimitResponse(allowed=False)

    # permissions

    async def CheckUserPermission(self, request, context):
        try:
            has_permission = await self._service.check_user_permission(
                request.user_id, request.required_scope
            )
            return auth_pb2.CheckUserPermissionResponse(has_permission=has_permission)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.CheckUserPermissionResponse(has_permission=False)

    async def CheckAPIKeyScope(self, request, context):
        try:
            has_scope = await self._service.check_api_key_scope(
                request.api_key_id, request.required_scope
            )
            return auth_pb2.CheckAPIKeyScopeResponse(has_scope=has_scope)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return auth_pb2.CheckAPIKeyScopeResponse(has_scope=False)

    # conversion helpers

    @staticmethod
    def _dict_to_user(d: dict) -> auth_pb2.User:
        return auth_pb2.User(
            id=d["id"],
            email=d["email"],
            plan_tier=PLAN_TIER_REVERSE.get(d["plan_tier"], auth_pb2.PLAN_TIER_FREE),
            role=ROLE_REVERSE.get(d["role"], auth_pb2.ROLE_MEMBER),
            created_at=d.get("created_at") or 0.0,
            updated_at=d.get("updated_at") or 0.0,
            is_active=d.get("is_active", True),
        )

    @staticmethod
    def _dict_to_api_key(d: dict) -> auth_pb2.APIKey:
        return auth_pb2.APIKey(
            id=d["id"],
            user_id=d["user_id"],
            name=d["name"],
            rate_limit_per_minute=d["rate_limit_per_minute"],
            scopes=d.get("scopes", []),
            created_at=d.get("created_at") or 0.0,
            last_used_at=d.get("last_used_at"),
            is_active=d.get("is_active", True),
        )
