import time
import uuid
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr


class PlanTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    password_hash: str
    plan_tier: PlanTier = PlanTier.FREE
    role: Role = Role.MEMBER
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    is_active: bool = True

    def to_redis_record(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "password_hash": self.password_hash,
            "plan_tier": self.plan_tier.value,
            "role": self.role.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_active": str(self.is_active).lower(),
        }

    @classmethod
    def from_redis_record(cls, data: Dict[str, Any]) -> "User":
        return cls(
            id=data["id"],
            email=data["email"],
            password_hash=data["password_hash"],
            plan_tier=PlanTier(data["plan_tier"]),
            role=Role(data.get("role", Role.MEMBER.value)),
            created_at=float(data["created_at"]),
            updated_at=float(data["updated_at"]),
            is_active=data["is_active"].lower() == "true",
        )


class APIKey(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    key_hash: str
    name: str = "Default API Key"
    rate_limit_per_minute: int = 1000
    scopes: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    last_used_at: Optional[float] = None
    is_active: bool = True

    def to_redis_record(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "key_hash": self.key_hash,
            "name": self.name,
            "rate_limit_per_minute": str(self.rate_limit_per_minute),
            "scopes": ",".join(self.scopes),
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "is_active": str(self.is_active).lower(),
        }

    @classmethod
    def from_redis_record(cls, data: Dict[str, Any]) -> "APIKey":
        scopes = data.get("scopes", "").split(",") if data.get("scopes") else []
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            key_hash=data["key_hash"],
            name=data["name"],
            rate_limit_per_minute=int(data["rate_limit_per_minute"]),
            scopes=[s.strip() for s in scopes if s.strip()],
            created_at=float(data["created_at"]),
            last_used_at=(
                float(data["last_used_at"]) if data.get("last_used_at") else None
            ),
            is_active=data["is_active"].lower() == "true",
        )


class UsageRecord(BaseModel):
    api_key_id: str
    date: str
    requests_count: int = 0

    def to_redis_record(self) -> Dict[str, Any]:
        return {
            "api_key_id": self.api_key_id,
            "date": self.date,
            "requests_count": str(self.requests_count),
        }

    @classmethod
    def from_redis_record(cls, data: Dict[str, Any]) -> "UsageRecord":
        return cls(
            api_key_id=data["api_key_id"],
            date=data["date"],
            requests_count=int(data["requests_count"]),
        )
