from __future__ import annotations

from fastapi import FastAPI
from qbrixlog import get_logger
from qbrixstore.redis.client import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.invalidation import TenantInvalidation
from proxysvc.ee.entitlements import PlanEntitlements
from proxysvc.ee.plans import CLOUD_FEATURES

logger = get_logger(__name__)


def entitlements(
    settings: ProxySettings, redis: RedisClient, offered: frozenset[str]
) -> PlanEntitlements:
    return PlanEntitlements(
        redis=redis, settings=settings, offered=offered | CLOUD_FEATURES
    )


# billing is imported inside the two hooks below, not at module scope: the
# router pulls in the http auth dependencies, which bind the auth operator at
# import time, and entitlements() runs before the runtime has initialised it.


def register_components(settings: ProxySettings, bus: TenantInvalidation) -> None:
    from proxysvc.ee.billing.router import set_billing_service
    from proxysvc.ee.billing.service import BillingService

    _verify_billing_config(settings)
    billing = BillingService(announcer=bus)
    bus.register(billing.invalidate_tenant)
    set_billing_service(billing)


def register_routes(app: FastAPI) -> None:
    from proxysvc.ee.billing.router import router

    app.include_router(router, prefix="/api/v1")


def _verify_billing_config(settings: ProxySettings) -> None:
    """warn about tiers stripe can charge for but this proxy cannot resolve.

    a price id that matches no configured tier is refused at checkout and
    blocks webhook provisioning, so say which ones are missing at boot
    rather than at the first upgrade. not fatal: a deployment may sell only
    some tiers.
    """
    if not settings.stripe_secret_key:
        return
    missing = [
        name
        for name, value in (
            ("PROXY_STRIPE_PRICE_ID_STARTER", settings.stripe_price_id_starter),
            ("PROXY_STRIPE_PRICE_ID_GROWTH", settings.stripe_price_id_growth),
            ("PROXY_STRIPE_PRICE_ID_SCALE", settings.stripe_price_id_scale),
            ("PROXY_STRIPE_PRICE_ID_ENTERPRISE", settings.stripe_price_id_enterprise),
        )
        if not value
    ]
    if missing:
        logger.warning(
            "stripe is configured but these plan prices are not: "
            f"{', '.join(missing)} — checkout for those tiers will be refused"
        )
