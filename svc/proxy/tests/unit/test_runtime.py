"""the runtime starts the safety watch only with qbrix next switched on."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import proxysvc.runtime as runtime_module
from proxysvc.config import ProxySettings
from proxysvc.runtime import ProxyRuntime

pytestmark = pytest.mark.unit


class _Component:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.redis = object()
        self.loops = object()
        self.entitlements = SimpleNamespace(invalidate=lambda tenant: None)

    async def connect(self):
        pass

    async def close(self):
        pass

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def register(self, callback):
        pass


@pytest.fixture
def watches(monkeypatch) -> list[_Component]:
    built: list[_Component] = []

    def watch(*args, **kwargs):
        built.append(_Component(*args, **kwargs))
        return built[-1]

    monkeypatch.setattr(runtime_module, "init_db", lambda settings: None)
    monkeypatch.setattr(runtime_module, "RedisClient", _Component)
    monkeypatch.setattr(runtime_module, "ProxyService", _Component)
    monkeypatch.setattr(runtime_module, "TenantInvalidation", _Component)
    monkeypatch.setattr(
        runtime_module,
        "create_auth_service",
        lambda redis, entitlements: SimpleNamespace(invalidate_tenant=None),
    )
    monkeypatch.setattr(runtime_module, "init_operators", lambda auth: None)
    monkeypatch.setattr(
        runtime_module.edition, "register_components", lambda settings, bus: None
    )
    monkeypatch.setattr(runtime_module, "SafetyWatch", watch)
    return built


def _settings(**overrides) -> ProxySettings:
    return ProxySettings(runenv="dev", clickhouse_host="clickhouse", **overrides)


async def test_no_watch_runs_with_next_off(watches):
    async with ProxyRuntime(_settings(next_enabled=False)):
        pass

    assert watches == []


async def test_the_watch_runs_with_next_on_and_stops_with_the_runtime(watches):
    async with ProxyRuntime(_settings(next_enabled=True, safety_interval_sec=15)):
        (watch,) = watches
        assert watch.started and not watch.stopped
        assert watch.kwargs == {"interval_sec": 15}

    assert watch.stopped


def test_the_interval_stays_under_the_lease():
    with pytest.raises(ValueError):
        _settings(safety_interval_sec=60)
