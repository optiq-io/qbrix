from __future__ import annotations

from types import ModuleType

from fastapi import FastAPI
from qbrixstore.redis.client import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.entitlements import Entitlements
from proxysvc.core.entitlements import UnlimitedEntitlements
from proxysvc.core.invalidation import TenantInvalidation

OFFERED_FEATURES = frozenset({"rbac", "insights", "event_log"})


def entitlements(settings: ProxySettings, redis: RedisClient) -> Entitlements:
    if not settings.ee_enabled:
        return UnlimitedEntitlements(OFFERED_FEATURES)
    return _ee().entitlements(settings, redis, OFFERED_FEATURES)


def register_components(settings: ProxySettings, bus: TenantInvalidation) -> None:
    if settings.ee_enabled:
        _ee().register_components(settings, bus)


def register_routes(app: FastAPI, settings: ProxySettings) -> None:
    if settings.ee_enabled:
        _ee().register_routes(app)


def _ee() -> ModuleType:
    try:
        import proxysvc.ee
    except ModuleNotFoundError as e:
        if e.name != "proxysvc.ee":
            raise
        raise RuntimeError(
            "PROXY_EE_ENABLED is set but the proxysvc.ee package is not installed"
        ) from e
    return proxysvc.ee
