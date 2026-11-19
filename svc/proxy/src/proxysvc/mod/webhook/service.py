from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from qbrixstore.postgres.models import Webhook
from qbrixstore.postgres.models import WebhookDelivery
from qbrixstore.postgres.session import get_session

from proxysvc.config import ProxySettings
from proxysvc.core.actor import Actor
from proxysvc.core.entitlements import Entitlements
from proxysvc.core.error import WebhookNotFoundError
from proxysvc.core.secretbox import SecretBox
from proxysvc.core.secretbox import SecretUnreadableError
from proxysvc.mod.people import People
from proxysvc.mod.webhook.repository import WebhookRepository
from proxysvc.mod.webhook.rule import masked
from proxysvc.mod.webhook.sender import Attempt
from proxysvc.mod.webhook.sender import WebhookSender

logger = logging.getLogger(__name__)

SECRET_LABEL = "webhook-secret"
SECRET_PREFIX = "whsec_"
RECENT_DELIVERIES = 5

ALERT = "alert"
TEST = "test"

PENDING = "pending"
DELIVERED = "delivered"
FAILING = "failing"
GAVE_UP = "gave_up"
# a single attempt that is never retried, as a test send is
FAILED = "failed"

UNREADABLE = "the signing secret can't be read; regenerate it"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    """sqlite hands timestamps back naive; postgres keeps the zone."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _utc(value)
    return value.isoformat() if value else None


def _person(people: People, user_id: str | None) -> dict | None:
    if not user_id:
        return None
    return {"id": user_id, "name": people.name(user_id)}


class WebhookService:
    """the workspace's one webhook: where qbrix posts alerts, and the secret
    it signs them with.

    it is a setting an admin manages, not a change: nothing here records a
    change, and the secret leaves qbrix only in the response that made it.
    """

    def __init__(
        self,
        *,
        settings: ProxySettings,
        entitlements: Entitlements,
        sender: WebhookSender | None = None,
        clock: Callable[[], datetime] = _now,
    ):
        self._box = SecretBox(settings.derived_key(SECRET_LABEL))
        self._entitlements = entitlements
        self._sender = sender or WebhookSender()
        self._clock = clock

    @property
    def public_only(self) -> bool:
        return self._entitlements.edition == "cloud"

    def secret_of(self, webhook: Webhook) -> str:
        """the webhook's signing secret; raises SecretUnreadableError when the
        box key changed since it was sealed."""
        return self._box.open(
            webhook.secret_ciphertext,
            tenant_id=webhook.tenant_id,
            purpose=SECRET_LABEL,
            row_id=webhook.id,
        )

    async def configured(self, tenant_id: str) -> bool:
        async with get_session() as session:
            return await WebhookRepository(session, tenant_id).exists()

    async def read(self, tenant_id: str, *, reveal: bool = False) -> dict:
        async with get_session() as session:
            repo = WebhookRepository(session, tenant_id)
            webhook = await repo.get()
            deliveries = await repo.recent_deliveries(RECENT_DELIVERIES)
            people = await People.load(
                session,
                tenant_id,
                [webhook.created_by if webhook else ""]
                + [d.sent_by or "" for d in deliveries],
            )
        if webhook is None:
            return {"configured": False, "deliveries": []}
        found = {
            "configured": True,
            "url_masked": masked(webhook.url),
            "secret_hint": webhook.secret_hint,
            "created_by": _person(people, webhook.created_by),
            "created_at": _iso(webhook.created_at),
            "updated_at": _iso(webhook.updated_at),
            "deliveries": [_delivery(d, people) for d in deliveries],
        }
        if reveal:
            found["url"] = webhook.url
        return found

    async def put(self, tenant_id: str, url: str, *, actor: Actor) -> dict:
        """set the workspace's url. the first time also makes the secret, and
        the result carries it this once; replacing the url keeps it."""
        await self._sender.check(url, public_only=self.public_only)
        try:
            secret = await self._put(tenant_id, url, actor)
        except IntegrityError:
            # another admin created it first; this request replaces their url
            secret = await self._put(tenant_id, url, actor)
        found = await self.read(tenant_id)
        if secret is not None:
            found["secret"] = secret
        return found

    async def _put(self, tenant_id: str, url: str, actor: Actor) -> str | None:
        async with get_session() as session:
            repo = WebhookRepository(session, tenant_id)
            webhook = await repo.get()
            if webhook is not None:
                webhook.url = url
                logger.info(
                    f"webhook url replaced in tenant {tenant_id} by {actor.user_id}"
                )
                return None
            webhook = Webhook(
                id=uuid4().hex, tenant_id=tenant_id, url=url, created_by=actor.user_id
            )
            secret = self._seal_new_secret(webhook)
            repo.add(webhook)
            await session.flush()
        logger.info(f"webhook added in tenant {tenant_id} by {actor.user_id}")
        return secret

    async def regenerate(self, tenant_id: str, *, actor: Actor) -> dict:
        async with get_session() as session:
            webhook = await WebhookRepository(session, tenant_id).get()
            if webhook is None:
                raise WebhookNotFoundError("the workspace has no webhook")
            secret = self._seal_new_secret(webhook)
        logger.info(
            f"webhook secret regenerated in tenant {tenant_id} by {actor.user_id}"
        )
        found = await self.read(tenant_id)
        found["secret"] = secret
        return found

    async def remove(self, tenant_id: str, *, actor: Actor) -> None:
        async with get_session() as session:
            removed = await WebhookRepository(session, tenant_id).delete()
        if not removed:
            raise WebhookNotFoundError("the workspace has no webhook")
        logger.info(f"webhook removed in tenant {tenant_id} by {actor.user_id}")

    def log_reveal(self, tenant_id: str, *, actor: Actor) -> None:
        logger.info(f"webhook url revealed in tenant {tenant_id} by {actor.user_id}")

    async def test(self, tenant_id: str, *, actor: Actor) -> dict:
        """send a test message now and keep it as a delivery. a secret that
        can't be read fails the test without sending: never unsigned."""
        async with get_session() as session:
            repo = WebhookRepository(session, tenant_id)
            webhook = await repo.get()
            if webhook is None:
                raise WebhookNotFoundError("the workspace has no webhook")
            workspace = await repo.workspace_name()
            people = await People.load(session, tenant_id, [actor.user_id])
        name = people.name(actor.user_id)
        delivery_id = uuid4().hex
        sent_at = self._clock()
        text = f"Test from {name} · qbrix"
        payload = {
            "text": text,
            "kind": TEST,
            "workspace": {"name": workspace},
            "sent_by": {"name": name},
            "sent_at": sent_at.isoformat(),
        }

        try:
            secret = self.secret_of(webhook)
        except SecretUnreadableError:
            logger.warning(f"webhook secret unreadable in tenant {tenant_id}")
            attempt = Attempt(at=sent_at, error=UNREADABLE)
        else:
            attempt = await self._sender.send(
                webhook.url,
                secret,
                delivery_id,
                payload,
                public_only=self.public_only,
            )

        delivery = WebhookDelivery(
            id=delivery_id,
            tenant_id=tenant_id,
            kind=TEST,
            summary=text,
            payload=payload,
            status=DELIVERED if attempt.ok else FAILED,
            attempts=1,
            results=[attempt.to_dict()],
            last_status_code=attempt.status_code,
            last_error=attempt.error,
            first_attempt_at=attempt.at,
            delivered_at=attempt.at if attempt.ok else None,
            sent_by=actor.user_id,
            created_at=sent_at,
        )
        async with get_session() as session:
            repo = WebhookRepository(session, tenant_id)
            current = await repo.get()
            if current is not None and current.id == webhook.id:
                repo.add_delivery(delivery)
        return _delivery(delivery, people)

    def _seal_new_secret(self, webhook: Webhook) -> str:
        secret = SECRET_PREFIX + secrets.token_urlsafe(32)
        webhook.secret_ciphertext = self._box.seal(
            secret, tenant_id=webhook.tenant_id, purpose=SECRET_LABEL, row_id=webhook.id
        )
        webhook.secret_hint = secret[-4:]
        return secret


def _delivery(delivery: WebhookDelivery, people: People) -> dict:
    return {
        "id": delivery.id,
        "kind": delivery.kind,
        "summary": delivery.summary,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "results": delivery.results,
        "last_status_code": delivery.last_status_code,
        "last_error": delivery.last_error,
        "sent_by": _person(people, delivery.sent_by),
        "created_at": _iso(delivery.created_at),
        "delivered_at": _iso(delivery.delivered_at),
    }
