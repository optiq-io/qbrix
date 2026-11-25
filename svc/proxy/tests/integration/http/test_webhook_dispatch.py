"""integration tests for sending alerts to the workspace webhook, a qbrix
next surface.

invariants verified:
  an alert opening or ending queues a notice in its own transaction, and
  only when the workspace has a webhook. notices wait a minute, so alerts
  that open together arrive as one signed message. a safety pause goes out
  within the minute and a person's resume sends one recovery naming them; a
  warning sends one message while open and one when it clears. a failure
  retries on a backing-off schedule and holds later deliveries behind it,
  and a day after its first try it gives up and the next one goes. only the
  lease holder sends; a holder that dies mid-send leaves the delivery to be
  sent once more under the same id. an unreadable secret never sends.
  removing the webhook drops what hasn't been sent.
"""

from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func
from sqlalchemy import select

from qbrixstore.postgres.models import Alert
from qbrixstore.postgres.models import AlertNotice
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User
from qbrixstore.postgres.models import WebhookDelivery
from qbrixstore.postgres.session import get_session

from proxysvc.core.actor import Actor
from proxysvc.mod.safety.rule import OUTCOMES_STOPPED
from proxysvc.mod.safety.service import CLEARED
from proxysvc.mod.safety.service import AlertService
from proxysvc.mod.webhook.dispatch import LEASE
from proxysvc.mod.webhook.dispatch import WebhookDispatch
from proxysvc.mod.webhook.sender import WebhookSender
from proxysvc.mod.webhook.service import DELIVERED
from proxysvc.mod.webhook.service import FAILING
from proxysvc.mod.webhook.service import GAVE_UP
from proxysvc.mod.webhook.service import UNREADABLE
from proxysvc.mod.webhook.service import WebhookService

TENANT = "dev-tenant"
ADA = "user-ada"
ADMIN = Actor.member(ADA)
SLACK = "https://hooks.slack.com/services/T0/B0/abcdef"
ORIGIN = "https://console.acme.test"
PAUSE = {"signal": "decision_errors", "rate": 0.072, "errors": 30, "calls": 412}
STOPPED = {"signal": OUTCOMES_STOPPED, "decisions_since_outcome": 1240}
OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
]


class _Receiver:
    """the other end of the webhook: records each request and answers the
    scripted statuses in turn, then the last one forever."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.statuses = [200]

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            status = (
                self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            )
            return httpx.Response(status)

        return httpx.MockTransport(handle)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


class _Edition:
    edition = "cloud"


async def _public(host: str) -> list[str]:
    return ["93.184.216.34"]


def _webhooks(wired_app, receiver: _Receiver, *, box_key: str | None = None):
    settings = wired_app.svc._settings
    if box_key is not None:
        settings = settings.model_copy(update={"secret_box_key": box_key})
    return WebhookService(
        settings=settings,
        entitlements=_Edition(),
        sender=WebhookSender(resolver=_public, transport=receiver.transport()),
    )


def _dispatch(wired_app, webhooks: WebhookService) -> WebhookDispatch:
    return WebhookDispatch(
        wired_app.svc.redis, webhooks, console_origin=ORIGIN, interval_sec=10
    )


@pytest.fixture
def receiver() -> _Receiver:
    return _Receiver()


@pytest_asyncio.fixture
async def workspace(wired_app, next_enabled):
    async with get_session() as session:
        session.add(Tenant(id=TENANT, name="Acme", slug="acme"))
        session.add(
            User(
                id=ADA,
                tenant_id=TENANT,
                email="ada@example.com",
                password_hash="x",
                name="Ada",
            )
        )
    await wired_app.svc.create_metric(
        TENANT,
        name="purchase",
        semantic="a completed checkout",
        metric_type="conversion",
        window_seconds=2 * 24 * 60 * 60,
        actor=ADMIN,
    )


@pytest_asyncio.fixture
async def webhooks(wired_app, workspace, receiver) -> WebhookService:
    service = _webhooks(wired_app, receiver)
    await service.put(TENANT, SLACK, actor=ADMIN)
    return service


@pytest.fixture
def dispatch(wired_app, webhooks) -> WebhookDispatch:
    return _dispatch(wired_app, webhooks)


def _later(seconds: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


async def _loop(wired_app, name: str = "Search ranking") -> dict:
    loop = (
        await wired_app.svc.create_loop(
            TENANT, name=name, metric="purchase", options=OPTIONS, actor=ADMIN
        )
    ).value
    return (await wired_app.svc.launch_loop(TENANT, loop["key"], actor=ADMIN)).value


async def _safety_pause(wired_app, loop: dict) -> None:
    await wired_app.svc.loops.pause_loop(
        TENANT,
        loop["key"],
        actor=Actor.qbrix(),
        reason="decision errors",
        evidence=PAUSE,
    )


async def _warn(loop: dict):
    async with get_session() as session:
        return await AlertService(session, TENANT).open(
            loop["id"], OUTCOMES_STOPPED, STOPPED
        )


async def _clear(alert) -> None:
    async with get_session() as session:
        alert = await session.merge(alert)
        await AlertService(session, TENANT).resolve(alert, CLEARED, Actor.qbrix())


async def _notices() -> int:
    async with get_session() as session:
        return (await session.execute(select(func.count(AlertNotice.id)))).scalar_one()


async def _deliveries() -> list[WebhookDelivery]:
    async with get_session() as session:
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.kind == "alert")
            .order_by(WebhookDelivery.created_at, WebhookDelivery.id)
        )
        return list((await session.execute(stmt)).scalars())


async def test_a_safety_pause_is_one_message_within_the_minute(
    wired_app, dispatch, receiver
):
    loop = await _loop(wired_app)
    await _safety_pause(wired_app, loop)

    await dispatch.run_once(_later(30))
    assert receiver.requests == []

    await dispatch.run_once(_later(70))
    (body,) = receiver.bodies()
    assert body["text"] == (
        "qbrix paused Search ranking: 7% of its decisions failed. Everyone gets"
        f" the fallback until a person resumes it. {ORIGIN}/loops/{loop['key']}"
    )
    assert body["kind"] == "alert"
    assert body["workspace"] == {"name": "Acme"}
    assert "sent_at" in body
    (item,) = body["alerts"]
    assert item["event"] == "opened"
    assert item["loop"] == {"key": loop["key"], "name": "Search ranking"}
    assert item["value"]["calls"] == 412
    (delivery,) = await _deliveries()
    assert delivery.status == DELIVERED
    assert delivery.summary == body["text"]
    assert receiver.requests[0].headers["qbrix-delivery"] == delivery.id

    await dispatch.run_once(_later(140))
    assert len(receiver.requests) == 1


async def test_resuming_sends_one_recovery_naming_who(wired_app, dispatch, receiver):
    loop = await _loop(wired_app)
    await _safety_pause(wired_app, loop)
    await dispatch.run_once(_later(70))

    await wired_app.svc.resume_loop(TENANT, loop["key"], actor=ADMIN)
    await dispatch.run_once(_later(140))

    assert len(receiver.requests) == 2
    body = receiver.bodies()[1]
    assert body["text"].startswith(
        "Search ranking resumed by Ada after 1 min on the fallback."
    )
    (item,) = body["alerts"]
    assert item["event"] == "recovered"
    assert item["resolution"] == "resumed"
    assert item["resolved_by"] == "Ada"


async def test_a_warning_sends_once_while_open_and_once_when_it_clears(
    wired_app, dispatch, receiver
):
    loop = await _loop(wired_app)
    alert = await _warn(loop)
    await _warn(loop)
    await dispatch.run_once(_later(70))
    await dispatch.run_once(_later(80))

    await _clear(alert)
    await dispatch.run_once(_later(140))

    texts = [b["text"] for b in receiver.bodies()]
    assert len(texts) == 2
    assert texts[0].startswith("Search ranking stopped receiving outcomes")
    assert texts[1].startswith("Search ranking is receiving outcomes again.")


async def test_alerts_on_three_loops_in_one_minute_are_one_message(
    wired_app, dispatch, receiver
):
    for name in ("Search ranking", "Checkout button", "Home banner"):
        await _safety_pause(wired_app, await _loop(wired_app, name))

    await dispatch.run_once(_later(70))

    (body,) = receiver.bodies()
    assert body["text"].split("\n")[0] == "3 loops need a look in Acme"
    assert [a["loop"]["name"] for a in body["alerts"]] == [
        "Search ranking",
        "Checkout button",
        "Home banner",
    ]


async def test_a_failing_delivery_retries_and_holds_later_ones_behind_it(
    wired_app, dispatch, receiver
):
    receiver.statuses = [502, 502, 200]
    first = await _loop(wired_app)
    await _safety_pause(wired_app, first)
    await dispatch.run_once(_later(70))

    await _safety_pause(wired_app, await _loop(wired_app, "Checkout button"))
    await dispatch.run_once(_later(80))
    assert len(receiver.requests) == 1
    held, waiting = await _deliveries()
    assert held.status == FAILING
    assert waiting.status == "pending"

    await dispatch.run_once(_later(101))
    await dispatch.run_once(_later(140))
    assert len(receiver.requests) == 2

    await dispatch.run_once(_later(162))
    held, waiting = await _deliveries()
    assert held.status == DELIVERED
    assert [r["status_code"] for r in held.results] == [502, 502, 200]
    assert held.attempts == 3
    assert waiting.status == "pending"
    assert {r.headers["qbrix-delivery"] for r in receiver.requests} == {held.id}

    await dispatch.run_once(_later(172))
    assert receiver.requests[-1].headers["qbrix-delivery"] == waiting.id


async def test_an_endpoint_down_for_a_day_gives_up_and_the_next_goes(
    wired_app, dispatch, receiver
):
    receiver.statuses = [503]
    await _safety_pause(wired_app, await _loop(wired_app))
    start = _later(70)
    await dispatch.run_once(start)
    await _safety_pause(wired_app, await _loop(wired_app, "Checkout button"))

    for _ in range(40):
        held = (await _deliveries())[0]
        if held.status == GAVE_UP:
            break
        await dispatch.run_once(held.next_attempt_at.replace(tzinfo=timezone.utc))
    assert held.status == GAVE_UP
    assert held.first_attempt_at.replace(tzinfo=timezone.utc) == start
    # the first try, six backing off, hourly to the day's end, and one at it
    assert held.attempts == 1 + 6 + 23 + 1

    receiver.statuses = [200]
    await dispatch.run_once(start + timedelta(hours=24, seconds=10))
    _, next_one = await _deliveries()
    assert next_one.status == DELIVERED


async def test_only_the_lease_holder_sends(wired_app, webhooks, receiver):
    holder = _dispatch(wired_app, webhooks)
    other = _dispatch(wired_app, webhooks)
    await _safety_pause(wired_app, await _loop(wired_app))

    await holder.run_once(_later(70))
    await other.run_once(_later(70))
    await other.run_once(_later(200))

    assert len(receiver.requests) == 1


async def test_a_holder_that_dies_mid_send_leaves_one_resend(
    wired_app, webhooks, receiver
):
    dying = _dispatch(wired_app, webhooks)
    real = webhooks.attempt

    async def sent_then_killed(*args, **kwargs):
        await real(*args, **kwargs)
        raise RuntimeError("killed")

    webhooks.attempt = sent_then_killed
    await _safety_pause(wired_app, await _loop(wired_app))
    await dying.run_once(_later(70))
    await wired_app.svc.redis.release_lease(LEASE, dying._holder)
    webhooks.attempt = real

    await _dispatch(wired_app, webhooks).run_once(_later(80))
    await _dispatch(wired_app, webhooks).run_once(_later(90))

    first, second = receiver.requests
    assert first.headers["qbrix-delivery"] == second.headers["qbrix-delivery"]
    (delivery,) = await _deliveries()
    assert delivery.status == DELIVERED
    assert delivery.attempts == 1


async def test_an_unreadable_secret_never_sends(wired_app, webhooks, receiver):
    other_key = _webhooks(wired_app, receiver, box_key="k" * 64)
    await _safety_pause(wired_app, await _loop(wired_app))

    await _dispatch(wired_app, other_key).run_once(_later(70))

    assert receiver.requests == []
    (delivery,) = await _deliveries()
    assert delivery.status == FAILING
    assert delivery.last_error == UNREADABLE


async def test_a_workspace_without_a_webhook_queues_nothing(
    wired_app, workspace, receiver
):
    loop = await _loop(wired_app)
    await _safety_pause(wired_app, loop)
    await wired_app.svc.resume_loop(TENANT, loop["key"], actor=ADMIN)

    assert await _notices() == 0


async def test_removing_the_webhook_drops_what_hasnt_been_sent(
    wired_app, webhooks, dispatch, receiver
):
    await _safety_pause(wired_app, await _loop(wired_app))
    assert await _notices() == 1

    await webhooks.remove(TENANT, actor=ADMIN)
    await dispatch.run_once(_later(70))

    assert await _notices() == 0
    assert receiver.requests == []
    async with get_session() as session:
        open_alerts = await session.execute(
            select(func.count(Alert.id)).where(Alert.resolved_at.is_(None))
        )
    assert open_alerts.scalar_one() == 1
