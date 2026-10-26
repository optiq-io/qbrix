"""fixtures for http integration tests."""

from __future__ import annotations

import time
import types
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

import qbrixstore.postgres.session as _session_module
from qbrixstore.clickhouse.ledger import CycleSpan
from qbrixstore.clickhouse.ledger import DecisionBucket
from qbrixstore.clickhouse.ledger import DecisionCount
from qbrixstore.clickhouse.ledger import SealedStats
from qbrixstore.postgres.models import Base
from qbrixstore.postgres.models import Tenant
from qbrixstore.redis.client import RedisClient

import proxysvc.config as _config_module
from proxysvc.mod.auth.operator import init_operators
from proxysvc.mod.auth.operator import AuthService
from proxysvc.config import ProxySettings
from proxysvc.core.events import EventEmitter
from proxysvc.mod.gate import GateService
from proxysvc.service import ProxyService
from proxysvc import edition

from svc.proxy.tests.conftest import RecordingSender

# ── spy publisher ─────────────────────────────────────────────────────────────


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


def _emitter_with_spies(feedback, selection, audit, metric) -> EventEmitter:
    """build an EventEmitter whose streams are spy publishers."""
    from qbrixstore.config import RedisSettings

    em = EventEmitter(RedisSettings())
    em._feedback = feedback
    em._selection = selection
    em._audit = audit
    em._metric = metric
    return em


# ── test settings ─────────────────────────────────────────────────────────────


def _make_test_settings() -> ProxySettings:
    return ProxySettings(
        runenv="dev",
        token_secret="test-secret-key-for-integration-tests",
        jwt_secret_key="test-jwt-secret",
        # postgres/redis values don't matter — we bypass start()
        postgres_host="localhost",
        redis_host="localhost",
        motor_host="localhost",
        cortex_host="localhost",
    )


# ── db fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_with_db(monkeypatch):
    """
    patch the global session module to point at an in-memory aiosqlite engine,
    create all tables, and restore the originals on teardown.

    function-scoped: each test gets a fresh db so there is no cross-test
    state bleed. the overhead is negligible for sqlite.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:  # noqa
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(_session_module, "_engine", engine)
    monkeypatch.setattr(_session_module, "_session_factory", factory)

    yield engine

    await engine.dispose()


# ── tenant fixtures ───────────────────────────────────────────────────────────
# these are separate so tests that don't need tenants skip the insert overhead


@pytest_asyncio.fixture
async def tenant_a(app_with_db) -> Tenant:
    """insert tenant-a into the test db."""
    async with _session_module.get_session() as session:
        tenant = Tenant(id="tenant-a", name="Tenant A", slug="tenant-a")
        session.add(tenant)
        await session.flush()
    return tenant


@pytest_asyncio.fixture
async def tenant_b(app_with_db) -> Tenant:
    """insert tenant-b into the test db."""
    async with _session_module.get_session() as session:
        tenant = Tenant(id="tenant-b", name="Tenant B", slug="tenant-b")
        session.add(tenant)
        await session.flush()
    return tenant


# ── ledger ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LedgerRow:
    cycle_id: str
    decision_id: str
    option_index: int
    opened_ms: int
    ledger_ms: int


@dataclass(frozen=True)
class SealedRow:
    cycle_id: str
    decision_id: str
    option_index: int
    opened_ms: int
    value: float | None


class FakeLedger:
    """the results queries of ClickHouseClient over in-memory rows, with
    the ledger's rules: a decision written twice counts once.

    ``delay`` makes every query block its thread, as a slow clickhouse does.
    """

    def __init__(self) -> None:
        self.decisions: list[LedgerRow] = []
        self.sealed: list[SealedRow] = []
        self.queries: list[str] = []
        self.delay = 0.0

    def connect(self, create_database: bool = True) -> None:
        pass

    def close(self) -> None:
        pass

    def decide(self, cycle_id, decision_id, option_index, opened_ms, ledger_ms=None):
        self.decisions.append(
            LedgerRow(
                cycle_id, decision_id, option_index, opened_ms, ledger_ms or opened_ms
            )
        )

    def seal(self, cycle_id, decision_id, option_index, opened_ms, value):
        self.sealed.append(
            SealedRow(cycle_id, decision_id, option_index, opened_ms, value)
        )

    def _ran(self, name: str) -> None:
        self.queries.append(name)
        if self.delay:
            time.sleep(self.delay)

    def _once(self, rows) -> list:
        return list({row.decision_id: row for row in rows}.values())

    def decision_series(self, tenant_id, cycle_id, since_ms, until_ms, step_ms):
        self._ran("decision_series")
        counts: dict = defaultdict(int)
        for row in self._once(
            r
            for r in self.decisions
            if r.cycle_id == cycle_id and since_ms <= r.opened_ms < until_ms
        ):
            counts[(row.opened_ms // step_ms * step_ms, row.option_index)] += 1
        return [DecisionBucket(b, i, n) for (b, i), n in sorted(counts.items())]

    def decision_counts(self, tenant_id, spans: list[CycleSpan], complete_up_to_ms):
        self._ran("decision_counts")
        cut = complete_up_to_ms if complete_up_to_ms is not None else 2**63 - 1
        sealed = {(r.cycle_id, r.decision_id) for r in self.sealed}
        out = []
        for span in spans:
            by_option: dict = defaultdict(lambda: [0, 0, 0])
            for row in self._once(
                r
                for r in self.decisions
                if r.cycle_id == span.cycle_id
                and span.since_ms <= r.opened_ms < span.until_ms
            ):
                counts = by_option[row.option_index]
                counts[0] += 1
                if row.ledger_ms < cut:
                    counts[1 if (row.cycle_id, row.decision_id) in sealed else 2] += 1
            out += [DecisionCount(span.cycle_id, i, *c) for i, c in by_option.items()]
        return out

    def sealed_stats(self, tenant_id, spans: list[CycleSpan]):
        self._ran("sealed_stats")
        out = []
        for span in spans:
            by_option: dict = defaultdict(lambda: [0, 0.0, 0.0])
            for row in self._once(
                r
                for r in self.sealed
                if r.cycle_id == span.cycle_id
                and span.since_ms <= r.opened_ms < span.until_ms
                and r.value is not None
            ):
                stats = by_option[row.option_index]
                stats[0] += 1
                stats[1] += row.value
                stats[2] += row.value * row.value
            out += [SealedStats(span.cycle_id, i, *s) for i, s in by_option.items()]
        return out


# ── fakeredis ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def fake_redis_client() -> AsyncGenerator[FakeRedis, Any]:
    """isolated fakeredis instance per test."""
    client = FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


# ── wired_app ─────────────────────────────────────────────────────────────────


class _WiredApp(types.SimpleNamespace):
    """namespace giving tests access to all injected doubles."""


@pytest_asyncio.fixture
async def wired_app(
    app_with_db, fake_redis_client: FakeRedis, monkeypatch
) -> AsyncGenerator[_WiredApp, Any]:
    """
    build a ProxyService with injected test doubles and wire it into
    all http routers.  skips svc.start() entirely — no postgres/redis
    network calls, no grpc connections.

    yields a _WiredApp namespace with:
        app           — the fastapi application
        svc           — ProxyService instance
        audit_spy     — SpyPublisher for audit events
        selection_spy — SpyPublisher for selection events
        feedback_spy  — SpyPublisher for feedback events
        metric_spy    — SpyPublisher for metric events
        motor_mock    — AsyncMock for MotorClient
        gate_mock     — AsyncMock for GateService
        fake_redis    — FakeRedis instance (already connected to RedisClient)
    """
    from proxysvc.transport.http.app import app
    from proxysvc.transport.http.router.agent import set_proxy_service as set_agent
    from proxysvc.transport.http.router.connection import (
        set_proxy_service as set_connection,
    )
    from proxysvc.transport.http.router.experiment import (
        set_proxy_service as set_experiment,
    )
    from proxysvc.transport.http.router.gate import set_proxy_service as set_gate
    from proxysvc.transport.http.router.loop import set_proxy_service as set_loop
    from proxysvc.transport.http.router.metric import set_proxy_service as set_metric
    from proxysvc.transport.http.router.oauth import set_proxy_service as set_oauth
    from proxysvc.transport.http.router.outcome import (
        set_proxy_service as set_outcome,
    )
    from proxysvc.transport.http.router.pool import set_proxy_service as set_pool
    from proxysvc.transport.http.router.runtime import set_proxy_service as set_runtime
    from proxysvc.transport.http.router.select import set_proxy_service as set_select

    test_settings = _make_test_settings()
    monkeypatch.setattr(_config_module.settings, "runenv", "dev")
    svc = ProxyService(test_settings)

    # wire fakeredis — RedisClient wraps the underlying redis client;
    # we inject the FakeRedis instance directly into _client so all
    # redis operations (get_experiment, set_experiment, etc.) work.
    redis_client = RedisClient()
    redis_client._client = fake_redis_client
    svc._redis = redis_client

    # initialize auth operators so require_scopes / get_current_user
    # dependencies work.  AuthService needs redis for rate limiting.
    from proxysvc.core.email import EmailService

    svc._entitlements = edition.entitlements(test_settings, redis_client)
    auth_svc = AuthService(
        redis_client, EmailService(RecordingSender()), svc.entitlements
    )
    init_operators(auth_svc)

    # gRPC clients — not on the hot path for management tests
    svc._motor_client = AsyncMock()
    svc._motor_client.health = AsyncMock(return_value=True)  # noqa
    svc._cortex_client = AsyncMock()
    svc._cortex_client.health = AsyncMock(return_value=True)  # noqa

    # event egress — one EventEmitter whose streams are spies that capture
    # every emitted event.  fire-and-forget dispatch is real; tests call
    # `await wired_app.events.drain()` before asserting on the spies.
    feedback_spy = SpyPublisher()
    selection_spy = SpyPublisher()
    audit_spy = SpyPublisher()
    metric_spy = SpyPublisher()
    events = _emitter_with_spies(feedback_spy, selection_spy, audit_spy, metric_spy)
    svc._events = events

    # gate service — backed by fakeredis so set_config/get_config/delete_config
    # all work correctly through the two-level cache.  tests that need gate
    # control can interact directly with gate_svc or replace _gate_service.
    # shares the same emitter so gate-config crud events land in the audit spy.
    gate_svc = GateService(redis_client, test_settings, events=events)
    svc._gate_service = gate_svc

    ledger = FakeLedger()
    svc._clickhouse = ledger

    # assemble per-domain sub-services from the injected collaborators
    svc._build_services()

    # wire routers
    set_pool(svc)
    set_experiment(svc)
    set_gate(svc)
    set_agent(svc)
    set_runtime(svc)
    set_metric(svc)
    set_loop(svc)
    set_select(svc)
    set_outcome(svc)
    set_connection(svc)
    set_oauth(svc)

    wired = _WiredApp(
        app=app,
        svc=svc,
        events=events,
        audit_spy=audit_spy,
        selection_spy=selection_spy,
        feedback_spy=feedback_spy,
        metric_spy=metric_spy,
        motor_mock=svc._motor_client,  # noqa
        gate_svc=gate_svc,
        fake_redis=fake_redis_client,
        ledger=ledger,
    )

    yield wired

    # teardown: reset router module globals so they don't bleed into other tests
    set_pool(None)  # type: ignore[arg-type]
    set_experiment(None)  # type: ignore[arg-type]
    set_gate(None)  # type: ignore[arg-type]
    set_agent(None)  # type: ignore[arg-type]
    set_runtime(None)  # type: ignore[arg-type]
    set_metric(None)  # type: ignore[arg-type]
    set_loop(None)  # type: ignore[arg-type]
    set_select(None)  # type: ignore[arg-type]
    set_outcome(None)  # type: ignore[arg-type]
    set_connection(None)  # type: ignore[arg-type]
    set_oauth(None)  # type: ignore[arg-type]


# ── http client ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(wired_app: _WiredApp) -> AsyncGenerator[AsyncClient, Any]:
    """
    async httpx client bound to the real fastapi app via ASGITransport.
    no network — all requests are dispatched in-process.
    """
    transport = ASGITransport(app=wired_app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── cross-tenant identity helper ─────────────────────────────────────────────


@contextmanager
def as_tenant(
    app,
    tenant_id: str,
    user_id: str = "user-x",
    role: str = "admin",
    plan_tier: str = "enterprise",
):
    """
    context manager that overrides the identity dependencies on the fastapi app
    so that requests appear to originate from a different tenant/user.

    overrides:
        get_current_tenant_id  → returns tenant_id
        get_current_user_id    → returns user_id
        get_current_user       → returns a minimal user-like object with the
                                 given role and plan_tier (default "enterprise"
                                 so scope checks pass without touching the db).

    restores all overrides on exit, regardless of exceptions.

    usage:
        with as_tenant(wired_app.app, tenant_id="tenant-a", plan_tier="free"):
            response = await client.get("/api/v1/event")
    """
    from proxysvc.transport.http.auth.dependencies import (
        get_current_tenant_id,
        get_current_user_id,
        get_current_user,
    )

    class _FakeUser:
        def __init__(self) -> None:
            self.id = user_id
            self.tenant_id = tenant_id
            self.role = role
            self.plan_tier = plan_tier
            self.is_active = True
            self.name = user_id
            self.email = f"{user_id}@example.com"

    async def _tenant() -> str:
        return tenant_id

    async def _user_id() -> str:
        return user_id

    async def _user() -> _FakeUser:
        return _FakeUser()

    previous = {
        get_current_tenant_id: app.dependency_overrides.get(get_current_tenant_id),
        get_current_user_id: app.dependency_overrides.get(get_current_user_id),
        get_current_user: app.dependency_overrides.get(get_current_user),
    }

    app.dependency_overrides[get_current_tenant_id] = _tenant
    app.dependency_overrides[get_current_user_id] = _user_id
    app.dependency_overrides[get_current_user] = _user

    try:
        yield
    finally:
        for dep, orig in previous.items():
            if orig is None:
                app.dependency_overrides.pop(dep, None)
            else:
                app.dependency_overrides[dep] = orig
