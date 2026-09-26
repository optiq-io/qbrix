"""unit tests for AuthService business logic."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest

from proxysvc.config import ProxySettings
from proxysvc.mod.auth.scope import ABUSE_RATE_LIMIT_PER_MINUTE
from proxysvc.mod.auth.scope import ROLE_SCOPES
from proxysvc.mod.auth.service import AuthService
from proxysvc import edition

from proxysvc.core.email import EmailService
from proxysvc.core.email import NullSender

from svc.proxy.tests.conftest import RecordingSender


def _make_user_record(plan_tier="free", **overrides):
    """create a mock user ORM object.

    plan_tier is the tenant's — users carry no tier of their own — and is
    accepted here so a fixture states it once, next to the user it belongs to.
    """
    defaults = {
        "id": "u-1",
        "tenant_id": "t-1",
        "email": "test@example.com",
        "name": "Test User",
        "password_hash": "$2b$12$fakehash",
        "role": "member",
        "is_active": True,
        "email_verified": False,
        "email_verified_at": None,
        "created_at": datetime(2024, 1, 1),
        "updated_at": datetime(2024, 1, 1),
    }
    defaults.update(overrides)
    record = MagicMock()
    for k, v in defaults.items():
        setattr(record, k, v)
    # the tier is read off the tenant, and every user load eagerly carries it
    record.tenant = _make_tenant_record(id=defaults["tenant_id"], plan_tier=plan_tier)
    # hasattr check for 'name'
    record.__contains__ = lambda self, item: item in defaults
    return record


def _make_api_key_record(**overrides):
    """create a mock api key ORM object."""
    defaults = {
        "id": "key-1",
        "user_id": "u-1",
        "key_hash": "abc123",
        "name": "Test Key",
        "rate_limit_per_minute": 100,
        "scopes": ["pool:read"],
        "is_active": True,
        "created_at": datetime(2024, 1, 1),
        "last_used_at": None,
    }
    defaults.update(overrides)
    record = MagicMock()
    for k, v in defaults.items():
        setattr(record, k, v)
    return record


def _make_tenant_record(**overrides):
    """create a mock tenant ORM object."""
    defaults = {
        "id": "t-1",
        "name": "Test Workspace",
        "slug": "test",
        "plan_tier": "free",
        "created_at": datetime(2024, 1, 1),
    }
    defaults.update(overrides)
    record = MagicMock()
    for k, v in defaults.items():
        setattr(record, k, v)
    return record


def _make_mock_pipeline(get_return=None):
    """create a mock redis pipeline that returns results on execute()."""
    pipe = MagicMock()
    pipe.get = MagicMock(return_value=pipe)
    pipe.incr = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[get_return, None, None])
    return pipe


@pytest.fixture
def mock_redis_client():
    redis = AsyncMock()
    redis.client = AsyncMock()
    redis.client.get = AsyncMock(return_value=None)
    redis.client.incr = AsyncMock()
    redis.client.expire = AsyncMock()
    redis.client.pipeline = MagicMock(return_value=_make_mock_pipeline())
    return redis


@pytest.fixture
def auth_service(mock_redis_client):
    return AuthService(
        mock_redis_client,
        EmailService(RecordingSender()),
        edition.entitlements(ProxySettings(), mock_redis_client),
    )


class TestAuthServiceRegister:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_creates_tenant_when_no_tenant_id(
        self, mock_bcrypt, mock_get_session, auth_service
    ):
        mock_bcrypt.gensalt.return_value = b"$2b$12$salt"
        mock_bcrypt.hashpw.return_value = b"$2b$12$hashed"

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email = AsyncMock(return_value=None)
        user = _make_user_record(email="alice@example.com")
        mock_user_repo.create = AsyncMock(return_value=user)

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get_by_slug = AsyncMock(return_value=None)
        tenant = _make_tenant_record(id="t-new", slug="alice")
        mock_tenant_repo.create = AsyncMock(return_value=tenant)

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.TenantRepository",
                return_value=mock_tenant_repo,
            ),
        ):
            result = await auth_service.register_user(
                email="alice@example.com",
                password="secret123",
            )

        assert result["email"] == "alice@example.com"
        mock_tenant_repo.create.assert_called_once()
        create_call = mock_tenant_repo.create.call_args
        assert create_call.kwargs["slug"] == "alice"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_uses_provided_tenant_id(
        self, mock_bcrypt, mock_get_session, auth_service
    ):
        mock_bcrypt.gensalt.return_value = b"$2b$12$salt"
        mock_bcrypt.hashpw.return_value = b"$2b$12$hashed"

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email = AsyncMock(return_value=None)
        user = _make_user_record(tenant_id="t-existing")
        mock_user_repo.create = AsyncMock(return_value=user)

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch("proxysvc.mod.auth.service.TenantRepository") as mock_tenant_cls,
        ):
            result = await auth_service.register_user(
                email="bob@example.com",
                password="secret123",
                tenant_id="t-existing",
            )

        assert result["tenant_id"] == "t-existing"
        # tenant repo should not have been instantiated for creation
        mock_tenant_cls.return_value.create.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_duplicate_email_raises(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        existing_user = _make_user_record()
        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email = AsyncMock(return_value=existing_user)

        with patch(
            "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
        ):
            with pytest.raises(ValueError, match="already exists"):
                await auth_service.register_user(
                    email="test@example.com",
                    password="secret123",
                )

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_slug_collision_increments(
        self, mock_bcrypt, mock_get_session, auth_service
    ):
        mock_bcrypt.gensalt.return_value = b"$2b$12$salt"
        mock_bcrypt.hashpw.return_value = b"$2b$12$hashed"

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email = AsyncMock(return_value=None)
        user = _make_user_record()
        mock_user_repo.create = AsyncMock(return_value=user)

        # slug "alice" exists, "alice-1" does not
        mock_tenant_repo = AsyncMock()
        existing_tenant = _make_tenant_record(slug="alice")
        mock_tenant_repo.get_by_slug = AsyncMock(
            side_effect=lambda slug: existing_tenant if slug == "alice" else None
        )
        new_tenant = _make_tenant_record(id="t-new", slug="alice-1")
        mock_tenant_repo.create = AsyncMock(return_value=new_tenant)

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.TenantRepository",
                return_value=mock_tenant_repo,
            ),
        ):
            await auth_service.register_user(
                email="alice@example.com",
                password="secret123",
            )

        create_call = mock_tenant_repo.create.call_args
        assert create_call.kwargs["slug"] == "alice-1"


class TestPlanTierComesFromTheTenant:
    """_user_to_dict is the single funnel every principal read flows through.

    users.plan_tier is still written by the billing fan-out, so these fixtures
    deliberately diverge the two columns: the tenant must win everywhere.
    """

    @staticmethod
    def _diverged_user():
        user = _make_user_record(plan_tier="free")
        user.tenant = _make_tenant_record(plan_tier="growth")
        return user

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_get_user_reports_the_tenant_tier(
        self, mock_get_session, auth_service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=self._diverged_user())

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await auth_service.get_user("u-1")

        assert result["plan_tier"] == "growth"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_authenticate_reports_the_tenant_tier(
        self, mock_get_session, auth_service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = self._diverged_user()
        user.password_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode("utf-8")
        mock_repo = AsyncMock()
        mock_repo.get_by_email = AsyncMock(return_value=user)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await auth_service.authenticate_user("test@example.com", "secret")

        assert result["plan_tier"] == "growth"


class TestInvalidateTenant:
    """the tier is a tenant property, but it reaches callers embedded in each
    member's cached principal — so eviction has to sweep a user-keyed cache."""

    @staticmethod
    def _cache_principals(auth_service):
        auth_service._user_cache["u-1"] = {"id": "u-1", "tenant_id": "t-1"}
        auth_service._user_cache["u-2"] = {"id": "u-2", "tenant_id": "t-1"}
        auth_service._user_cache["u-3"] = {"id": "u-3", "tenant_id": "t-2"}

    def test_evicts_every_member_of_the_tenant(self, auth_service):
        self._cache_principals(auth_service)

        auth_service.invalidate_tenant("t-1")

        assert auth_service._user_cache.get("u-1") is None
        assert auth_service._user_cache.get("u-2") is None

    def test_leaves_other_tenants_cached(self, auth_service):
        """a blanket clear() would pass the eviction test and silently cost
        every other tenant a database read."""
        self._cache_principals(auth_service)

        auth_service.invalidate_tenant("t-1")

        assert auth_service._user_cache.get("u-3") == {"id": "u-3", "tenant_id": "t-2"}

    def test_unknown_tenant_is_a_noop(self, auth_service):
        self._cache_principals(auth_service)

        auth_service.invalidate_tenant("t-nope")

        assert len(auth_service._user_cache) == 3

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_next_get_user_rereads_the_tier(self, mock_get_session, auth_service):
        """the behaviour callers actually depend on: after eviction the
        principal is rebuilt from the database, not served stale."""
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        free = _make_user_record()
        upgraded = _make_user_record()
        upgraded.tenant = _make_tenant_record(id="t-1", plan_tier="growth")

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(side_effect=[free, upgraded])

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            assert (await auth_service.get_user("u-1"))["plan_tier"] == "free"
            # without eviction this is served from cache and stays free
            auth_service.invalidate_tenant("t-1")
            assert (await auth_service.get_user("u-1"))["plan_tier"] == "growth"


class TestAuthServiceAuthenticate:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_valid_credentials(self, mock_bcrypt, mock_get_session, auth_service):
        mock_bcrypt.checkpw.return_value = True

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record()
        mock_repo = AsyncMock()
        mock_repo.get_by_email = AsyncMock(return_value=user)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await auth_service.authenticate_user("test@example.com", "correct")

        assert result is not None
        assert result["id"] == "u-1"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_wrong_password(self, mock_bcrypt, mock_get_session, auth_service):
        mock_bcrypt.checkpw.return_value = False

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record()
        mock_repo = AsyncMock()
        mock_repo.get_by_email = AsyncMock(return_value=user)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await auth_service.authenticate_user("test@example.com", "wrong")

        assert result is None

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_inactive_user(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(is_active=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_email = AsyncMock(return_value=user)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await auth_service.authenticate_user("test@example.com", "secret")

        assert result is None

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_nonexistent_email(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get_by_email = AsyncMock(return_value=None)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await auth_service.authenticate_user(
                "nobody@example.com", "secret"
            )

        assert result is None


class TestAuthServiceAPIKey:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_create_with_role_scopes(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(role="member", plan_tier="free")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        api_key = _make_api_key_record(scopes=["experiment:read", "experiment:write"])
        mock_key_repo = AsyncMock()
        mock_key_repo.count_by_tenant = AsyncMock(return_value=0)
        mock_key_repo.create = AsyncMock(return_value=api_key)

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_key_repo
            ),
        ):
            result_dict, plain_key = await auth_service.create_api_key("u-1")

        assert plain_key.startswith("optiq_")
        assert result_dict["id"] == "key-1"
        # scopes arg should be the role scopes (no explicit scopes passed)
        create_call = mock_key_repo.create.call_args
        assert "scopes" in create_call.kwargs

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_revoked_key_frees_a_slot(self, mock_get_session, auth_service):
        """the count is of active keys, so revoking one lets the tenant create again."""
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(plan_tier="free")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        # 2 keys issued, 1 since revoked
        mock_key_repo = AsyncMock()
        mock_key_repo.count_by_tenant = AsyncMock(return_value=1)
        mock_key_repo.create = AsyncMock(return_value=_make_api_key_record())

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_key_repo
            ),
        ):
            _, plain_key = await auth_service.create_api_key("u-1")

        assert plain_key.startswith("optiq_")
        mock_key_repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_paid_tier_is_unlimited(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(plan_tier="growth")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        mock_key_repo = AsyncMock()
        mock_key_repo.count_by_tenant = AsyncMock(return_value=500)
        mock_key_repo.create = AsyncMock(return_value=_make_api_key_record())

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_key_repo
            ),
        ):
            _, plain_key = await auth_service.create_api_key("u-1")

        assert plain_key.startswith("optiq_")

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_validate_valid_key(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        api_key = _make_api_key_record(is_active=True)
        mock_repo = AsyncMock()
        mock_repo.get_by_hash = AsyncMock(return_value=api_key)
        mock_repo.update_last_used = AsyncMock()

        with patch(
            "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_repo
        ):
            result = await auth_service.validate_api_key("optiq_somevalidkey")

        assert result is not None
        assert result["id"] == "key-1"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_validate_inactive_key(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        api_key = _make_api_key_record(is_active=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_hash = AsyncMock(return_value=api_key)

        with patch(
            "proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_repo
        ):
            result = await auth_service.validate_api_key("optiq_somekey")

        assert result is None

    @pytest.mark.asyncio
    async def test_validate_wrong_prefix(self, auth_service):
        result = await auth_service.validate_api_key("badprefix_somekey")
        assert result is None


class TestAuthServiceChangePassword:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_change_password_success(self, mock_bcrypt, mock_get_session):
        mock_bcrypt.checkpw.return_value = True
        mock_bcrypt.gensalt.return_value = b"$2b$12$salt"
        mock_bcrypt.hashpw.return_value = b"$2b$12$newhash"

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(password_hash="$2b$12$oldhash")
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=user)
        mock_repo.update = AsyncMock()

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await AuthService.change_password("u-1", "oldpass", "newpass")

        assert result is True
        mock_repo.update.assert_called_once()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_change_password_wrong_current_raises(
        self, mock_bcrypt, mock_get_session
    ):
        mock_bcrypt.checkpw.return_value = False

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record()
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=user)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            with pytest.raises(ValueError, match="current password is incorrect"):
                await AuthService.change_password("u-1", "wrongpass", "newpass")

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_change_password_user_not_found(self, mock_get_session):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await AuthService.change_password("u-1", "pass", "newpass")

        assert result is False


class TestAuthServicePermissions:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_admin_has_any_scope(self, mock_get_session):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(role="admin")
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=user)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await AuthService.check_user_permission("u-1", "experiment:delete")

        assert result is True

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_viewer_lacks_write_scope(self, mock_get_session):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(role="viewer")
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=user)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await AuthService.check_user_permission("u-1", "experiment:write")

        assert result is False

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_viewer_has_read_scope(self, mock_get_session):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(role="viewer")
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=user)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await AuthService.check_user_permission("u-1", "experiment:read")

        assert result is True

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_nonexistent_user_denied(self, mock_get_session):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=None)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await AuthService.check_user_permission("u-missing", "pool:read")

        assert result is False

    def test_get_scopes_for_role_admin(self):
        scopes = AuthService.get_scopes_for_role("admin")
        assert "system:admin" in scopes

    def test_get_scopes_for_role_unknown(self):
        scopes = AuthService.get_scopes_for_role("unknown_role")
        assert scopes == []

    def test_role_scopes_are_hierarchical(self):
        """admin ⊇ member ⊇ viewer.

        http `require_scopes` tests scope membership literally against
        ROLE_SCOPES[role] without honouring the `system:admin` wildcard, so a
        scope granted to a lower role but missing from a higher one is a real
        403 for the higher role on any route gated on it.
        """
        admin = set(ROLE_SCOPES["admin"])
        member = set(ROLE_SCOPES["member"])
        viewer = set(ROLE_SCOPES["viewer"])

        assert member <= admin, f"member scopes missing from admin: {member - admin}"
        assert viewer <= member, f"viewer scopes missing from member: {viewer - member}"


class TestAuthServiceRateLimit:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_under_limit_allowed(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        api_key = _make_api_key_record(rate_limit_per_minute=100)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=api_key)

        # user rate limit check also needs to pass
        user = _make_user_record(plan_tier="growth")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        # pipeline returns low count
        auth_service._redis.client.pipeline = MagicMock(
            return_value=_make_mock_pipeline(get_return=b"5")
        )

        with (
            patch("proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_repo),
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
        ):
            allowed, remaining, limit = await auth_service.check_api_key_rate_limit(
                "key-1"
            )

        assert allowed is True
        assert limit == 100

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_over_limit_denied(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        api_key = _make_api_key_record(rate_limit_per_minute=100)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=api_key)

        user = _make_user_record(plan_tier="growth")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        # pipeline returns count at the limit
        auth_service._redis.client.pipeline = MagicMock(
            return_value=_make_mock_pipeline(get_return=b"100")
        )

        with (
            patch("proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_repo),
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
        ):
            allowed, remaining, limit = await auth_service.check_api_key_rate_limit(
                "key-1"
            )

        assert allowed is False
        assert remaining == 0
        assert limit == 100

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_unlimited_api_key_skips_key_limit(
        self, mock_get_session, auth_service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        api_key = _make_api_key_record(rate_limit_per_minute=-1)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=api_key)

        user = _make_user_record(plan_tier="enterprise")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        # per-user abuse check still runs; keep it under the ceiling
        auth_service._redis.client.pipeline = MagicMock(
            return_value=_make_mock_pipeline(get_return=b"5")
        )

        with (
            patch("proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_repo),
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
        ):
            allowed, remaining, limit = await auth_service.check_api_key_rate_limit(
                "key-1"
            )

        assert allowed is True
        assert limit == -1

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_user_rate_limit_uses_abuse_ceiling(
        self, mock_get_session, auth_service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        user = _make_user_record(plan_tier="enterprise")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        auth_service._redis.client.pipeline = MagicMock(
            return_value=_make_mock_pipeline(get_return=b"5")
        )

        with patch(
            "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
        ):
            allowed, remaining, limit = await auth_service.check_user_rate_limit("u-1")

        assert allowed is True
        assert limit == ABUSE_RATE_LIMIT_PER_MINUTE

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_finite_api_key_allowed_when_under_abuse_ceiling(
        self, mock_get_session, auth_service
    ):
        """finite per-key limit passes when both key and user counts are under."""
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        # api key has old baked-in limit from when user was on free plan
        api_key = _make_api_key_record(rate_limit_per_minute=100)
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=api_key)

        user = _make_user_record(plan_tier="enterprise")
        mock_user_repo = AsyncMock()
        mock_user_repo.get = AsyncMock(return_value=user)

        # pipeline returns count under the api key limit
        auth_service._redis.client.pipeline = MagicMock(
            return_value=_make_mock_pipeline(get_return=b"5")
        )

        with (
            patch("proxysvc.mod.auth.service.APIKeyRepository", return_value=mock_repo),
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
        ):
            allowed, remaining, limit = await auth_service.check_api_key_rate_limit(
                "key-1"
            )

        assert allowed is True


class TestAuthServiceEmailVerification:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_verify_email_marks_verified_and_is_single_use(
        self, mock_get_session, auth_service, mock_redis_client
    ):
        mock_redis_client.client.get = AsyncMock(return_value="u-1")

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock(
            return_value=_make_user_record(email_verified=True)
        )

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await auth_service.verify_email("tok-123")

        assert result is True
        # token consumed (single-use)
        mock_redis_client.client.delete.assert_awaited_once_with(
            "qbrix:email_verify:tok-123"
        )
        update_kwargs = mock_repo.update.call_args.kwargs
        assert update_kwargs["email_verified"] is True
        assert update_kwargs["email_verified_at"] is not None

    @pytest.mark.asyncio
    async def test_verify_email_invalid_token_returns_false(
        self, auth_service, mock_redis_client
    ):
        mock_redis_client.client.get = AsyncMock(return_value=None)

        result = await auth_service.verify_email("bad-token")

        assert result is False
        mock_redis_client.client.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_verify_email_unknown_user_does_not_consume_token(
        self, mock_get_session, auth_service, mock_redis_client
    ):
        mock_redis_client.client.get = AsyncMock(return_value="u-missing")

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock(return_value=None)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            result = await auth_service.verify_email("tok-123")

        assert result is False
        mock_redis_client.client.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_resend_verification_issues_token_for_unverified(
        self, mock_get_session, auth_service, mock_redis_client
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get_by_email = AsyncMock(
            return_value=_make_user_record(email_verified=False)
        )

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            await auth_service.resend_verification("test@example.com")

        mock_redis_client.client.set.assert_awaited_once()
        key = mock_redis_client.client.set.call_args.args[0]
        assert key.startswith("qbrix:email_verify:")

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_resend_verification_noop_when_already_verified(
        self, mock_get_session, auth_service, mock_redis_client
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get_by_email = AsyncMock(
            return_value=_make_user_record(email_verified=True)
        )

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            await auth_service.resend_verification("test@example.com")

        mock_redis_client.client.set.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_resend_verification_noop_when_unknown_email(
        self, mock_get_session, auth_service, mock_redis_client
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.get_by_email = AsyncMock(return_value=None)

        with patch("proxysvc.mod.auth.service.UserRepository", return_value=mock_repo):
            await auth_service.resend_verification("nobody@example.com")

        mock_redis_client.client.set.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.settings")
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_register_dev_mode_auto_verifies_without_token(
        self,
        mock_bcrypt,
        mock_get_session,
        mock_settings,
        auth_service,
        mock_redis_client,
    ):
        mock_settings.runenv = "dev"
        mock_settings.signup_mode = "open"
        mock_bcrypt.gensalt.return_value = b"$2b$12$salt"
        mock_bcrypt.hashpw.return_value = b"$2b$12$hashed"

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email = AsyncMock(return_value=None)
        mock_user_repo.create = AsyncMock(
            return_value=_make_user_record(email_verified=True)
        )

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get_by_slug = AsyncMock(return_value=None)
        mock_tenant_repo.create = AsyncMock(return_value=_make_tenant_record())

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.TenantRepository",
                return_value=mock_tenant_repo,
            ),
        ):
            await auth_service.register_user(email="dev@example.com", password="pw")

        # dev users are created already-verified and no verification token is issued
        assert mock_user_repo.create.call_args.kwargs["email_verified"] is True
        mock_redis_client.client.set.assert_not_called()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.settings")
    @patch("proxysvc.mod.auth.service.get_session")
    @patch("proxysvc.mod.auth.service.bcrypt")
    async def test_register_non_dev_issues_token(
        self,
        mock_bcrypt,
        mock_get_session,
        mock_settings,
        auth_service,
        mock_redis_client,
    ):
        mock_settings.runenv = "prod"
        mock_settings.signup_mode = "open"
        mock_settings.console_origin = "https://cloud.qbrix.io"
        mock_settings.email_verification_ttl_seconds = 86400
        mock_bcrypt.gensalt.return_value = b"$2b$12$salt"
        mock_bcrypt.hashpw.return_value = b"$2b$12$hashed"

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email = AsyncMock(return_value=None)
        mock_user_repo.create = AsyncMock(
            return_value=_make_user_record(email_verified=False)
        )

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get_by_slug = AsyncMock(return_value=None)
        mock_tenant_repo.create = AsyncMock(return_value=_make_tenant_record())

        with (
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
            patch(
                "proxysvc.mod.auth.service.TenantRepository",
                return_value=mock_tenant_repo,
            ),
        ):
            await auth_service.register_user(email="prod@example.com", password="pw")

        assert mock_user_repo.create.call_args.kwargs["email_verified"] is False
        mock_redis_client.client.set.assert_awaited_once()
        assert mock_redis_client.client.set.call_args.args[0].startswith(
            "qbrix:email_verify:"
        )


def _make_invite_record(**overrides):
    """create a mock invite ORM object."""
    defaults = {
        "id": "inv-1",
        "tenant_id": "t-1",
        "email": "invitee@example.com",
        "role": "member",
        "status": "pending",
        "token": "invite-token-abc",
        "invited_by": "u-1",
        "expires_at": datetime(2024, 1, 4),
        "created_at": datetime(2024, 1, 1),
    }
    defaults.update(overrides)
    record = MagicMock()
    for k, v in defaults.items():
        setattr(record, k, v)
    return record


class TestAuthServiceGetWorkspace:

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_member_count_is_a_count_not_a_row_load(
        self, mock_get_session, auth_service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get = AsyncMock(return_value=_make_tenant_record())

        mock_user_repo = AsyncMock()
        mock_user_repo.count_by_tenant = AsyncMock(return_value=4)

        with (
            patch(
                "proxysvc.mod.auth.service.TenantRepository",
                return_value=mock_tenant_repo,
            ),
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
        ):
            result = await AuthService.get_workspace("t-1")

        assert result["member_count"] == 4
        assert result["id"] == "t-1"
        assert result["slug"] == "test"
        mock_user_repo.count_by_tenant.assert_awaited_once_with("t-1")
        mock_user_repo.list_by_tenant.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_counts_beyond_the_old_thousand_row_cap(
        self, mock_get_session, auth_service
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get = AsyncMock(return_value=_make_tenant_record())

        mock_user_repo = AsyncMock()
        mock_user_repo.count_by_tenant = AsyncMock(return_value=4200)

        with (
            patch(
                "proxysvc.mod.auth.service.TenantRepository",
                return_value=mock_tenant_repo,
            ),
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
        ):
            result = await AuthService.get_workspace("t-1")

        assert result["member_count"] == 4200

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_unknown_tenant_returns_none(self, mock_get_session, auth_service):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get = AsyncMock(return_value=None)

        mock_user_repo = AsyncMock()

        with (
            patch(
                "proxysvc.mod.auth.service.TenantRepository",
                return_value=mock_tenant_repo,
            ),
            patch(
                "proxysvc.mod.auth.service.UserRepository", return_value=mock_user_repo
            ),
        ):
            result = await AuthService.get_workspace("t-missing")

        assert result is None
        mock_user_repo.count_by_tenant.assert_not_awaited()


class TestAuthServiceCreateInvite:

    def _wire_repos(self, mock_get_session):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email = AsyncMock(return_value=None)
        mock_user_repo.count_by_tenant = AsyncMock(return_value=0)
        mock_user_repo.get = AsyncMock(
            return_value=_make_user_record(name="Alice", email="alice@example.com")
        )

        mock_invite_repo = AsyncMock()
        mock_invite_repo.get_pending_by_email_and_tenant = AsyncMock(return_value=None)
        mock_invite_repo.count_pending_by_tenant = AsyncMock(return_value=0)
        # mirror the DB: the persisted invite carries the token it was created with
        mock_invite_repo.create = AsyncMock(
            side_effect=lambda **kw: _make_invite_record(token=kw["token"])
        )

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get = AsyncMock(return_value=_make_tenant_record(name="Acme"))
        return mock_user_repo, mock_invite_repo, mock_tenant_repo

    def _patch_repos(self, user_repo, invite_repo, tenant_repo):
        return (
            patch("proxysvc.mod.auth.service.UserRepository", return_value=user_repo),
            patch(
                "proxysvc.mod.auth.service.InviteRepository", return_value=invite_repo
            ),
            patch(
                "proxysvc.mod.auth.service.TenantRepository", return_value=tenant_repo
            ),
        )

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.settings")
    @patch("proxysvc.mod.auth.service.secrets")
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_sends_invite_email_when_configured(
        self, mock_get_session, mock_secrets, mock_settings, auth_service
    ):
        mock_settings.console_origin = "https://cloud.qbrix.io"
        mock_secrets.token_urlsafe.return_value = "invite-token-abc"
        repos = self._wire_repos(mock_get_session)
        auth_service._email = AsyncMock()

        p1, p2, p3 = self._patch_repos(*repos)
        with p1, p2, p3:
            result = await auth_service.create_invite(
                tenant_id="t-1",
                email="invitee@example.com",
                role="member",
                invited_by="u-1",
            )

        expected_url = "https://cloud.qbrix.io/invite?token=invite-token-abc"
        assert result["invite_url"] == expected_url
        auth_service._email.send_workspace_invite.assert_awaited_once()
        kwargs = auth_service._email.send_workspace_invite.call_args.kwargs
        assert kwargs["to"] == "invitee@example.com"
        assert kwargs["invite_url"] == expected_url
        assert kwargs["inviter_name"] == "Alice"
        assert kwargs["workspace_name"] == "Acme"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.settings")
    @patch("proxysvc.mod.auth.service.secrets")
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_seat_check_counts_without_loading_members(
        self, mock_get_session, mock_secrets, mock_settings, auth_service
    ):
        mock_settings.console_origin = "https://cloud.qbrix.io"
        mock_secrets.token_urlsafe.return_value = "invite-token-abc"
        user_repo, invite_repo, tenant_repo = self._wire_repos(mock_get_session)

        p1, p2, p3 = self._patch_repos(user_repo, invite_repo, tenant_repo)
        with p1, p2, p3:
            await auth_service.create_invite(
                tenant_id="t-1",
                email="invitee@example.com",
                role="member",
                invited_by="u-1",
            )

        user_repo.count_by_tenant.assert_awaited_once_with("t-1")
        user_repo.list_by_tenant.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.settings")
    @patch("proxysvc.mod.auth.service.secrets")
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_no_email_when_unconfigured(
        self, mock_get_session, mock_secrets, mock_settings, auth_service
    ):
        mock_settings.console_origin = "https://cloud.qbrix.io"
        mock_secrets.token_urlsafe.return_value = "invite-token-abc"
        repos = self._wire_repos(mock_get_session)
        auth_service._email = EmailService(NullSender())

        p1, p2, p3 = self._patch_repos(*repos)
        with p1, p2, p3:
            result = await auth_service.create_invite(
                tenant_id="t-1",
                email="invitee@example.com",
                role="member",
                invited_by="u-1",
            )

        assert (
            result["invite_url"]
            == "https://cloud.qbrix.io/invite?token=invite-token-abc"
        )
        assert result["token"] == "invite-token-abc"

    @pytest.mark.asyncio
    @patch("proxysvc.mod.auth.service.settings")
    @patch("proxysvc.mod.auth.service.secrets")
    @patch("proxysvc.mod.auth.service.get_session")
    async def test_invite_survives_email_failure(
        self, mock_get_session, mock_secrets, mock_settings, auth_service
    ):
        mock_settings.console_origin = "https://cloud.qbrix.io"
        mock_secrets.token_urlsafe.return_value = "invite-token-abc"
        repos = self._wire_repos(mock_get_session)
        auth_service._email = AsyncMock()
        auth_service._email.send_workspace_invite = AsyncMock(
            side_effect=RuntimeError("resend down")
        )

        p1, p2, p3 = self._patch_repos(*repos)
        with p1, p2, p3:
            result = await auth_service.create_invite(
                tenant_id="t-1",
                email="invitee@example.com",
                role="member",
                invited_by="u-1",
            )

        assert (
            result["invite_url"]
            == "https://cloud.qbrix.io/invite?token=invite-token-abc"
        )
