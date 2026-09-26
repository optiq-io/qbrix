from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GRPCAuthContext:
    """authenticated identity resolved by the grpc auth interceptor."""

    tenant_id: str
    user_id: str
    role: str
    scopes: list[str] = field(default_factory=list)


_grpc_auth_context: ContextVar[GRPCAuthContext | None] = ContextVar(
    "grpc_auth_context", default=None
)


def get_grpc_auth_context() -> GRPCAuthContext | None:
    """get the current grpc auth context."""
    return _grpc_auth_context.get()


def set_grpc_auth_context(ctx: GRPCAuthContext | None) -> None:
    """set the grpc auth context for the current task."""
    _grpc_auth_context.set(ctx)
