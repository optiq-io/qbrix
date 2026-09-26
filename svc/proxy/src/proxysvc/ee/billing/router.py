from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, status

from qbrixlog import get_logger
from proxysvc.transport.http.auth.dependencies import (
    get_current_user,
    get_current_tenant_id,
    require_admin_user,
)
from proxysvc.transport.http.exception import (
    BadRequestException,
    ConflictException,
    InternalServerException,
    NotFoundException,
    UnknownPriceException,
)
from proxysvc.ee.billing.models import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    ChangeSubscriptionRequest,
    ChangePreviewResponse,
    PortalSessionRequest,
    PortalSessionResponse,
    SubscriptionResponse,
    UsageResponse,
    WebhookResponse,
)
from proxysvc.ee.billing.service import BillingService
from proxysvc.ee.billing.service import ActiveSubscriptionExistsError
from proxysvc.ee.billing.service import NoStripeCustomerError
from proxysvc.ee.billing.service import NoActiveSubscriptionError
from proxysvc.ee.billing.service import InvalidTierChangeError
from proxysvc.ee.billing.service import UnknownPriceError

logger = get_logger(__name__)

router = APIRouter(prefix="/ee/billing", tags=["ee-billing"])


# module-level billing service instance, set via set_billing_service()
_billing_service: Optional[BillingService] = None


def set_billing_service(service: BillingService) -> None:
    """set the billing service instance for this router."""
    global _billing_service
    _billing_service = service


def get_billing_service() -> BillingService:
    """get the billing service instance."""
    if _billing_service is None:
        raise RuntimeError("billing service not initialized")
    return _billing_service


@router.post(
    "/checkout/session",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_200_OK,
)
async def create_checkout_session(
    request: CheckoutSessionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(require_admin_user),
):
    """create a Stripe checkout session for subscription upgrade."""
    try:
        result = await get_billing_service().create_checkout_session(
            tenant_id=tenant_id,
            user_id=user.id,
            price_id=request.price_id,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
        )
        return result
    except ActiveSubscriptionExistsError:
        raise ConflictException(
            "an active subscription already exists; use the billing portal to change plans"
        )
    except UnknownPriceError as e:
        logger.error(f"checkout rejected: {e}")
        raise UnknownPriceException()
    except Exception as e:
        logger.error(f"failed to create checkout session: {e}")
        raise InternalServerException("failed to create checkout session")


@router.post(
    "/portal/session",
    response_model=PortalSessionResponse,
    status_code=status.HTTP_200_OK,
)
async def create_portal_session(
    request: PortalSessionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(require_admin_user),
):
    """create a Stripe billing portal session for subscription management."""
    try:
        return await get_billing_service().create_portal_session(
            tenant_id=tenant_id,
            return_url=request.return_url,
        )
    except NoStripeCustomerError:
        raise NotFoundException("no active subscription to manage")
    except Exception as e:
        logger.error(f"failed to create portal session: {e}")
        raise InternalServerException("failed to create portal session")


@router.post(
    "/subscription/change/preview",
    response_model=ChangePreviewResponse,
    status_code=status.HTTP_200_OK,
)
async def preview_subscription_change(
    request: ChangeSubscriptionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(require_admin_user),
):
    """preview the proration a tier change would apply, without committing."""
    try:
        return await get_billing_service().preview_subscription_change(
            tenant_id=tenant_id,
            target_tier=request.target_tier,
        )
    except InvalidTierChangeError as e:
        raise BadRequestException(str(e))
    except NoActiveSubscriptionError:
        raise NotFoundException("no active subscription to change")
    except Exception as e:
        logger.error(f"failed to preview subscription change: {e}")
        raise InternalServerException("failed to preview subscription change")


@router.post(
    "/subscription/change",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
)
async def change_subscription(
    request: ChangeSubscriptionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(require_admin_user),
):
    """upgrade or downgrade the subscription to another self-serve tier."""
    try:
        return await get_billing_service().change_subscription(
            tenant_id=tenant_id,
            target_tier=request.target_tier,
        )
    except InvalidTierChangeError as e:
        raise BadRequestException(str(e))
    except NoActiveSubscriptionError:
        raise NotFoundException("no active subscription to change")
    except Exception as e:
        logger.error(f"failed to change subscription: {e}")
        raise InternalServerException("failed to change subscription")


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
)
async def stripe_webhook(request: Request):
    """handle Stripe webhook events."""
    try:
        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")

        if not signature:
            logger.error("missing stripe-signature header")
            raise BadRequestException("missing signature")

        success = await get_billing_service().handle_webhook(payload, signature)

        if success:
            return {"received": True}
        else:
            raise BadRequestException("webhook processing failed")

    except Exception as e:
        logger.error(f"webhook error: {e}")
        raise BadRequestException("invalid webhook")


@router.get(
    "/subscription",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
)
async def get_subscription(
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(get_current_user),
):
    """get current subscription details."""
    subscription = await get_billing_service().get_subscription(tenant_id)

    if not subscription:
        # return inactive subscription for free tier
        return SubscriptionResponse(
            id="",
            plan_tier="free",
            status="inactive",
            current_period_start=0,
            current_period_end=0,
            cancel_at_period_end=False,
        )

    return subscription


@router.get(
    "/usage",
    response_model=UsageResponse,
    status_code=status.HTTP_200_OK,
)
async def get_usage(
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(get_current_user),
):
    """billed usage for the current period, sourced from stripe.

    metered self-serve tiers only (starter/growth/scale); free and enterprise
    have no metered stripe line, so this 404s for them.
    """
    try:
        usage = await get_billing_service().get_usage(tenant_id)
    except Exception as e:
        logger.error(f"failed to read usage: {e}")
        raise InternalServerException("failed to read usage")

    if usage is None:
        raise NotFoundException("usage is only available for metered plan tiers")

    return usage


@router.post(
    "/subscription/cancel",
    status_code=status.HTTP_200_OK,
)
async def cancel_subscription(
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(require_admin_user),
):
    """cancel subscription at period end."""
    try:
        success = await get_billing_service().cancel_subscription(tenant_id)

        if not success:
            raise NotFoundException("subscription not found")

        return {
            "status": "canceled",
            "message": "subscription will be canceled at period end",
        }
    except Exception as e:
        logger.error(f"failed to cancel subscription: {e}")
        raise InternalServerException("failed to cancel subscription")


@router.post(
    "/subscription/reactivate",
    status_code=status.HTTP_200_OK,
)
async def reactivate_subscription(
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(require_admin_user),
):
    """reactivate a canceled subscription."""
    try:
        success = await get_billing_service().reactivate_subscription(tenant_id)

        if not success:
            raise NotFoundException("subscription not found")

        return {
            "status": "reactivated",
            "message": "subscription has been reactivated",
        }
    except Exception as e:
        logger.error(f"failed to reactivate subscription: {e}")
        raise InternalServerException("failed to reactivate subscription")


@router.get(
    "/invoices",
    status_code=status.HTTP_200_OK,
)
async def list_invoices(
    tenant_id: str = Depends(get_current_tenant_id),
    user=Depends(get_current_user),
):
    """list billing history."""
    try:
        invoices = await get_billing_service().list_invoices(tenant_id)
        return {"invoices": invoices}
    except Exception as e:
        logger.error(f"failed to list invoices: {e}")
        raise InternalServerException("failed to list invoices")
