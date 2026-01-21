import logging
from typing import List
from typing import Literal
from typing import Optional

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import status
from fastapi import Depends
from pydantic import BaseModel
from pydantic import EmailStr

from proxysvc.http.auth.operator import auth_operator
from proxysvc.http.auth.operator import token_operator
from proxysvc.http.auth.dependencies import get_current_user_id
from proxysvc.http.auth.dependencies import get_current_user
from proxysvc.http.auth.dependencies import require_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

PlanTierType = Literal["free", "pro", "enterprise"]
RoleType = Literal["admin", "member", "viewer"]


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    plan_tier: PlanTierType = "free"
    role: RoleType = "member"


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    plan_tier: str
    role: str
    created_at: float
    is_active: bool


class LoginResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class APIKeyCreateRequest(BaseModel):
    name: str = "Default API Key"


class APIKeyResponse(BaseModel):
    id: str
    name: str
    key: str
    rate_limit_per_minute: int
    scopes: List[str]
    created_at: float
    is_active: bool


class APIKeyListResponse(BaseModel):
    id: str
    name: str
    rate_limit_per_minute: int
    scopes: List[str]
    created_at: float
    last_used_at: Optional[float] = None
    is_active: bool


class UsageResponse(BaseModel):
    current_minute_usage: int
    rate_limit_per_minute: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post(
    "/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse
)
async def register_user(body: UserRegisterRequest):
    try:
        user = await auth_operator.create_user(
            email=body.email,
            password=body.password,
            plan_tier=body.plan_tier,
            role=body.role,
        )

        logger.info(f"user registered successfully: {user.email}")
        return UserResponse(
            id=user.id,
            email=user.email,
            plan_tier=user.plan_tier,
            role=user.role,
            created_at=user.created_at,
            is_active=user.is_active,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"registration error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed",
        )


@router.post("/login", status_code=status.HTTP_200_OK, response_model=LoginResponse)
async def login_user(body: UserLoginRequest):
    user = await auth_operator.authenticate_user(body.email, body.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    access_token = token_operator.create_access_token(user)
    refresh_token = token_operator.create_refresh_token(user)

    logger.info(f"user logged in successfully: {user.email}")
    return LoginResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            plan_tier=user.plan_tier,
            role=user.role,
            created_at=user.created_at,
            is_active=user.is_active,
        ),
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh", status_code=status.HTTP_200_OK, response_model=RefreshTokenResponse
)
async def refresh_access_token(body: RefreshTokenRequest):
    access_token = await token_operator.refresh_access_token(body.refresh_token)
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return RefreshTokenResponse(access_token=access_token)


@router.post(
    "/api-keys", status_code=status.HTTP_201_CREATED, response_model=APIKeyResponse
)
async def create_api_key(
    body: APIKeyCreateRequest, user_id: str = Depends(get_current_user_id)
):

    try:
        api_key, plain_key = await auth_operator.create_api_key(user_id, body.name)

        logger.info(f"api key created for user {user_id}: {api_key.id}")
        return APIKeyResponse(
            id=api_key.id,
            name=api_key.name,
            key=plain_key,
            rate_limit_per_minute=api_key.rate_limit_per_minute,
            scopes=api_key.scopes,
            created_at=api_key.created_at,
            is_active=api_key.is_active,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"api key creation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key creation failed",
        )


@router.get(
    "/api-keys", status_code=status.HTTP_200_OK, response_model=List[APIKeyListResponse]
)
async def list_api_keys(user_id: str = Depends(get_current_user_id)):

    try:
        api_keys = await auth_operator.get_user_api_keys(user_id)

        return [
            APIKeyListResponse(
                id=key.id,
                name=key.name,
                rate_limit_per_minute=key.rate_limit_per_minute,
                scopes=key.scopes,
                created_at=key.created_at,
                last_used_at=key.last_used_at,
                is_active=key.is_active,
            )
            for key in api_keys
        ]
    except Exception as e:
        logger.error(f"api key listing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve API keys",
        )


@router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_200_OK)
async def deactivate_api_key(
    api_key_id: str, user_id: str = Depends(get_current_user_id)
):
    api_key = await auth_operator.get_api_key(api_key_id)
    if not api_key or api_key.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or access denied",
        )

    success = await auth_operator.deactivate_api_key(api_key_id, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Failed to deactivate API key"
        )

    logger.info(f"API key deactivated: {api_key_id} by user {user_id}")
    return {"message": "API key deactivated successfully"}


@router.get(
    "/api-keys/{api_key_id}/usage",
    status_code=status.HTTP_200_OK,
    response_model=UsageResponse,
)
async def get_api_key_usage(
    api_key_id: str, user_id: str = Depends(get_current_user_id)
):
    api_key = await auth_operator.get_api_key(api_key_id)
    if not api_key or api_key.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or access denied",
        )

    try:
        usage_stats = await auth_operator.get_api_key_usage(api_key)
        return UsageResponse(**usage_stats)
    except Exception as e:
        logger.error(f"usage stats error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage statistics",
        )


@router.get("/profile", status_code=status.HTTP_200_OK, response_model=UserResponse)
async def get_user_profile(user=Depends(get_current_user)):
    return UserResponse(
        id=user.id,
        email=user.email,
        plan_tier=user.plan_tier,
        role=user.role,
        created_at=user.created_at,
        is_active=user.is_active,
    )


class AssignRoleRequest(BaseModel):
    role: RoleType


@router.put("/users/{user_id}/role", status_code=status.HTTP_200_OK)
async def assign_role_to_user(
    user_id: str,
    body: AssignRoleRequest,
    admin_user=Depends(require_admin_user),
):
    success = await auth_operator.assign_role_to_user(user_id, body.role)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user not found"
        )

    logger.info(f"role {body.role} assigned to user {user_id}")
    return {"message": f"role {body.role} assigned successfully"}


@router.get("/roles", status_code=status.HTTP_200_OK)
async def list_roles():
    return {
        "roles": [
            {
                "name": "admin",
                "description": "full system access",
                "scopes": auth_operator.get_scopes_for_role("admin"),
            },
            {
                "name": "member",
                "description": "standard user access",
                "scopes": auth_operator.get_scopes_for_role("member"),
            },
            {
                "name": "viewer",
                "description": "read-only access",
                "scopes": auth_operator.get_scopes_for_role("viewer"),
            },
        ]
    }
