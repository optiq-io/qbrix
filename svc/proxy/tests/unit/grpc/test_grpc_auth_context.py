"""unit tests for grpc auth context module."""

import asyncio

import pytest

from proxysvc.transport.grpc.auth.context import (
    GRPCAuthContext,
    get_grpc_auth_context,
    set_grpc_auth_context,
)


class TestGRPCAuthContext:
    """tests for the GRPCAuthContext dataclass."""

    def test_create_context(self):
        ctx = GRPCAuthContext(
            tenant_id="t-1",
            user_id="u-1",
            role="admin",
            scopes=["pool:read", "pool:write"],
        )
        assert ctx.tenant_id == "t-1"
        assert ctx.user_id == "u-1"
        assert ctx.role == "admin"
        assert ctx.scopes == ["pool:read", "pool:write"]

    def test_frozen(self):
        ctx = GRPCAuthContext(tenant_id="t-1", user_id="u-1", role="member")
        with pytest.raises(AttributeError):
            ctx.tenant_id = "t-2"

    def test_default_scopes(self):
        ctx = GRPCAuthContext(tenant_id="t-1", user_id="u-1", role="viewer")
        assert ctx.scopes == []


class TestContextVar:
    """tests for the ContextVar-based get/set functions."""

    def test_default_is_none(self):
        assert get_grpc_auth_context() is None

    def test_set_and_get(self):
        ctx = GRPCAuthContext(tenant_id="t-1", user_id="u-1", role="admin")
        set_grpc_auth_context(ctx)
        assert get_grpc_auth_context() is ctx
        # cleanup
        set_grpc_auth_context(None)

    def test_set_none_clears(self):
        ctx = GRPCAuthContext(tenant_id="t-1", user_id="u-1", role="admin")
        set_grpc_auth_context(ctx)
        set_grpc_auth_context(None)
        assert get_grpc_auth_context() is None

    @pytest.mark.asyncio
    async def test_isolation_between_tasks(self):
        """context vars should be isolated between asyncio tasks."""
        results = {}

        async def task_a():
            ctx = GRPCAuthContext(tenant_id="t-a", user_id="u-a", role="admin")
            set_grpc_auth_context(ctx)
            await asyncio.sleep(0.01)
            results["a"] = get_grpc_auth_context()

        async def task_b():
            ctx = GRPCAuthContext(tenant_id="t-b", user_id="u-b", role="member")
            set_grpc_auth_context(ctx)
            await asyncio.sleep(0.01)
            results["b"] = get_grpc_auth_context()

        await asyncio.gather(task_a(), task_b())

        assert results["a"].tenant_id == "t-a"
        assert results["b"].tenant_id == "t-b"
