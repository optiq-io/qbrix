"""fixtures for grpc integration tests.

wiring is duplicated from tests/integration/http/conftest.py rather than
moved to tests/integration/conftest.py — the http conftest patches session
module globals which are only needed by the http test infrastructure, and
lifting them up would make the shared conftest import proxysvc http internals.
keeping the wiring isolated avoids accidental coupling between the two suites.
"""

from __future__ import annotations

import types
from typing import Any
from typing import AsyncGenerator
from unittest.mock import AsyncMock

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

import qbrixstore.postgres.session as _session_module
from qbrixstore.postgres.models import Base
from qbrixstore.postgres.models import Tenant
from qbrixstore.redis.client import RedisClient

from proxysvc.mod.auth.service import AuthService
from proxysvc.mod.auth.operator import init_operators
from proxysvc.config import ProxySettings
from proxysvc.core.events import EventEmitter
from proxysvc.mod.gate import GateService
from proxysvc.transport.grpc.auth.context import GRPCAuthContext
from proxysvc.transport.grpc.auth.context import set_grpc_auth_context
from proxysvc.server import ProxyGRPCServicer
from proxysvc.service import ProxyService
from proxysvc import edition

from svc.proxy.tests.conftest import RecordingSender


class SpyPublisher:
    """drop-in replacement for RedisStreamPublisher that records emitted events."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def publish(self, event: Any) -> None:
        self.events.append(event)


def _emitter_with_spies(feedback, selection, audit) -> EventEmitter:
    """build an EventEmitter whose three streams are spy publishers."""
    from qbrixstore.config import RedisSettings

    em = EventEmitter(RedisSettings(), selection=True, audit=True)
    em._feedback = feedback
    em._selection = selection
    em._audit = audit
    return em


def _make_test_settings() -> ProxySettings:
    return ProxySettings(
        runenv="dev",
        token_secret="test-secret-key-for-integration-tests",
        jwt_secret_key="test-jwt-secret",
        postgres_host="localhost",
        redis_host="localhost",
        motor_host="localhost",
        cortex_host="localhost",
    )


class _WiredGRPC(types.SimpleNamespace):
    """namespace giving gRPC integration tests access to all injected doubles."""


@pytest_asyncio.fixture
async def wired_grpc(monkeypatch) -> AsyncGenerator[_WiredGRPC, Any]:
    """
    build a ProxyGRPCServicer backed by in-memory aiosqlite + fakeredis.
    mirrors the wired_app pattern from tests/integration/http/conftest.py.

    yields a _WiredGRPC namespace with:
        servicer     — ProxyGRPCServicer instance (call methods directly)
        svc          — underlying ProxyService
        audit_spy    — SpyPublisher for audit events
        selection_spy — SpyPublisher for selection events
        feedback_spy  — SpyPublisher for feedback events
        motor_mock   — AsyncMock for MotorClient
        gate_svc     — GateService instance
        fake_redis   — FakeRedis instance
        engine       — SQLAlchemy async engine (for teardown)
    """
    from sqlalchemy import event as sa_event

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # enable FK enforcement so "missing experiment" tests work correctly
    @sa_event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, conn_record):  # type: ignore[misc]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(_session_module, "_engine", engine)
    monkeypatch.setattr(_session_module, "_session_factory", factory)

    # insert tenant-a
    async with _session_module.get_session() as session:
        tenant = Tenant(id="tenant-a", name="Tenant A", slug="tenant-a")
        session.add(tenant)
        await session.flush()

    fake_redis = FakeRedis(decode_responses=True)

    test_settings = _make_test_settings()
    svc = ProxyService(test_settings)

    redis_client = RedisClient()
    redis_client._client = fake_redis
    svc._redis = redis_client

    from proxysvc.core.email import EmailService

    svc._entitlements = edition.entitlements(test_settings, redis_client)
    auth_svc = AuthService(
        redis_client, EmailService(RecordingSender()), svc.entitlements
    )
    init_operators(auth_svc)

    svc._motor_client = AsyncMock()
    svc._motor_client.health = AsyncMock(return_value=True)
    svc._cortex_client = AsyncMock()
    svc._cortex_client.health = AsyncMock(return_value=True)

    feedback_spy = SpyPublisher()
    selection_spy = SpyPublisher()
    audit_spy = SpyPublisher()
    events = _emitter_with_spies(feedback_spy, selection_spy, audit_spy)
    svc._events = events

    gate_svc = GateService(redis_client, test_settings, events=events)
    svc._gate_service = gate_svc

    # assemble per-domain sub-services from the injected collaborators
    svc._build_services()

    servicer = ProxyGRPCServicer(svc)

    # set grpc auth context so servicer.* calls resolve the tenant
    set_grpc_auth_context(
        GRPCAuthContext(
            tenant_id="tenant-a",
            user_id="user-x",
            role="admin",
            scopes=["system:admin"],
        )
    )

    wired = _WiredGRPC(
        servicer=servicer,
        svc=svc,
        events=events,
        audit_spy=audit_spy,
        selection_spy=selection_spy,
        feedback_spy=feedback_spy,
        motor_mock=svc._motor_client,
        gate_svc=gate_svc,
        fake_redis=fake_redis,
        engine=engine,
    )

    yield wired

    set_grpc_auth_context(None)
    await fake_redis.aclose()
    await engine.dispose()
