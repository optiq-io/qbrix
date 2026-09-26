from __future__ import annotations

import stripe

from qbrixlog import get_logger

logger = get_logger(__name__)


class MeterEmitter:
    """emits summed selection counts to a Stripe billing meter.

    each call is idempotent on ``identifier``: stripe dedups repeated events
    with the same identifier, so re-emitting a (tenant, bucket) after a crash or
    retry does not double-count.
    """

    def __init__(self, secret_key: str, event_name: str):
        stripe.api_key = secret_key
        self._event_name = event_name

    def emit(
        self,
        stripe_customer_id: str,
        value: int,
        identifier: str,
        timestamp: int | None = None,
    ) -> bool:
        """report ``value`` selections for a customer. returns True on success.

        on any stripe error returns False so the caller does not ack the
        underlying stream messages and retries the bucket later.
        """
        try:
            stripe.billing.MeterEvent.create(
                event_name=self._event_name,
                identifier=identifier,
                payload={
                    "stripe_customer_id": stripe_customer_id,
                    "value": str(value),
                },
                timestamp=timestamp,
            )
            return True
        except stripe.StripeError as e:
            logger.error("stripe meter event failed for %s: %s", identifier, e)
            return False
