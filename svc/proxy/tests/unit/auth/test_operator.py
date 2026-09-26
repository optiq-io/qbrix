"""unit tests for TokenOperator and wrapper classes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from jose import jwt

from proxysvc.mod.auth.operator import TokenOperator, _UserWrapper, _APIKeyWrapper


@pytest.fixture
def token_op() -> TokenOperator:
    return TokenOperator(
        secret_key="test-jwt-secret",
        algorithm="HS256",
        access_token_expire_minutes=30,
        refresh_token_expire_days=7,
    )


def _make_user_obj(**overrides):
    """create a mock user object with attribute access."""
    defaults = {
        "id": "u-1",
        "tenant_id": "t-1",
        "email": "test@example.com",
        "role": "member",
        "plan_tier": "free",
        "is_active": True,
    }
    defaults.update(overrides)
    user = MagicMock()
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


class TestTokenOperator:

    def test_access_token_has_correct_claims(self, token_op):
        user = _make_user_obj()
        token = token_op.create_access_token(user)

        payload = jwt.decode(
            token,
            "test-jwt-secret",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert payload["sub"] == "u-1"
        assert payload["tenant_id"] == "t-1"
        assert payload["email"] == "test@example.com"
        assert payload["role"] == "member"
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_refresh_token_has_correct_claims(self, token_op):
        user = _make_user_obj()
        token = token_op.create_refresh_token(user)

        payload = jwt.decode(
            token,
            "test-jwt-secret",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert payload["sub"] == "u-1"
        assert payload["type"] == "refresh"
        assert "exp" in payload

    def test_verify_valid_token(self, token_op):
        user = _make_user_obj()
        token = token_op.create_access_token(user)

        payload = token_op.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "u-1"

    def test_verify_expired_token_returns_none(self, token_op):
        # craft a token that expired in the past
        payload = {
            "sub": "u-1",
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        token = jwt.encode(payload, "test-jwt-secret", algorithm="HS256")

        result = token_op.verify_token(token)
        assert result is None

    def test_verify_invalid_token_returns_none(self, token_op):
        result = token_op.verify_token("garbage.token.here")
        assert result is None

    def test_get_user_id_from_access_token(self, token_op):
        user = _make_user_obj()
        token = token_op.create_access_token(user)

        user_id = token_op.get_user_id_from_token(token)
        assert user_id == "u-1"

    def test_get_user_id_from_refresh_returns_none(self, token_op):
        user = _make_user_obj()
        token = token_op.create_refresh_token(user)

        user_id = token_op.get_user_id_from_token(token)
        assert user_id is None


class TestUserWrapper:

    def test_attribute_access(self):
        data = {
            "id": "u-1",
            "tenant_id": "t-1",
            "email": "user@test.com",
            "name": "Test User",
            "plan_tier": "growth",
            "role": "admin",
            "is_active": True,
            "created_at": 1000.0,
            "updated_at": 2000.0,
        }
        wrapper = _UserWrapper(data)

        assert wrapper.id == "u-1"
        assert wrapper.tenant_id == "t-1"
        assert wrapper.email == "user@test.com"
        assert wrapper.name == "Test User"
        assert wrapper.plan_tier == "growth"
        assert wrapper.role == "admin"
        assert wrapper.is_active is True
        assert wrapper.created_at == 1000.0
        assert wrapper.updated_at == 2000.0

    def test_is_active_defaults_true(self):
        data = {
            "id": "u-1",
            "tenant_id": "t-1",
            "email": "a@b.com",
            "plan_tier": "free",
            "role": "member",
        }
        wrapper = _UserWrapper(data)
        assert wrapper.is_active is True


class TestAPIKeyWrapper:

    def test_attribute_access(self):
        data = {
            "id": "key-1",
            "user_id": "u-1",
            "name": "My Key",
            "rate_limit_per_minute": 100,
            "scopes": ["pool:read", "pool:write"],
            "is_active": True,
            "created_at": 1000.0,
            "last_used_at": 2000.0,
        }
        wrapper = _APIKeyWrapper(data)

        assert wrapper.id == "key-1"
        assert wrapper.user_id == "u-1"
        assert wrapper.name == "My Key"
        assert wrapper.rate_limit_per_minute == 100
        assert wrapper.scopes == ["pool:read", "pool:write"]
        assert wrapper.is_active is True
        assert wrapper.created_at == 1000.0
        assert wrapper.last_used_at == 2000.0
