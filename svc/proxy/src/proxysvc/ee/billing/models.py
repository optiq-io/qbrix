from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CheckoutSessionRequest(BaseModel):
    price_id: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class CheckoutSessionResponse(BaseModel):
    session_id: str
    url: str


class PortalSessionRequest(BaseModel):
    return_url: Optional[str] = None


class PortalSessionResponse(BaseModel):
    url: str


class ChangeSubscriptionRequest(BaseModel):
    target_tier: str


class ChangePreviewResponse(BaseModel):
    target_tier: str
    currency: str
    proration_amount: int
    next_invoice_total: int


class SubscriptionResponse(BaseModel):
    id: str
    plan_tier: str
    status: str
    current_period_start: int
    current_period_end: int
    cancel_at_period_end: bool
    canceled_at: Optional[int] = None


class UsageResponse(BaseModel):
    used: int
    included: int
    overage: int
    overage_cost: int  # minor units (cents), stripe-rated metered line amount
    currency: str
    period_start: datetime
    period_end: datetime


class InvoiceResponse(BaseModel):
    id: str
    amount_due: int
    amount_paid: int
    currency: str
    status: str
    invoice_pdf: Optional[str] = None
    created_at: int


class WebhookResponse(BaseModel):
    received: bool
