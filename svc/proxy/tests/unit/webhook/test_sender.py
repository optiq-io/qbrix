"""a delivery is one signed post: the receiver can recompute the signature
over the raw body, a redirect is a failure and never followed, only a 2xx
counts, and in the cloud the request goes to the address that was vetted."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from proxysvc.mod.webhook import signature
from proxysvc.mod.webhook.sender import WebhookSender

pytestmark = pytest.mark.unit

SECRET = "whsec_test"
NOW = 1_763_550_000
PUBLIC = "93.184.216.34"
BODY = {"text": "Test from Ada · qbrix", "kind": "test"}


class _Receiver:
    def __init__(self, respond):
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._respond(request)

        return httpx.MockTransport(handle)


def _sender(receiver: _Receiver, *addresses: str) -> WebhookSender:
    async def resolve(host: str) -> list[str]:
        return list(addresses or (PUBLIC,))

    return WebhookSender(
        resolver=resolve, transport=receiver.transport(), clock=lambda: NOW
    )


def _verify(request: httpx.Request, secret: str) -> bool:
    parts = dict(p.split("=", 1) for p in request.headers["qbrix-signature"].split(","))
    expected = hmac.new(
        secret.encode(),
        f"{parts['t']}.".encode() + request.content,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])


async def test_a_2xx_is_delivered_and_the_signature_verifies():
    receiver = _Receiver(lambda r: httpx.Response(204))

    attempt = await _sender(receiver).send(
        "http://alerts.internal/hook", SECRET, "d1", BODY, public_only=False
    )

    assert attempt.ok and attempt.status_code == 204
    (request,) = receiver.requests
    assert str(request.url) == "http://alerts.internal/hook"
    assert request.headers["qbrix-delivery"] == "d1"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["user-agent"].startswith("qbrix/")
    assert request.headers["qbrix-signature"].startswith(f"t={NOW},v1=")
    assert json.loads(request.content) == BODY
    assert _verify(request, SECRET)
    assert not _verify(request, "whsec_other")


def test_the_signature_matches_a_known_vector():
    expected = hmac.new(b"s", b"1.{}", hashlib.sha256).hexdigest()

    assert signature.sign("s", 1, b"{}") == f"t=1,v1={expected}"


async def test_a_redirect_is_a_failure_never_followed():
    receiver = _Receiver(
        lambda r: httpx.Response(302, headers={"location": "http://10.0.0.1/"})
    )

    attempt = await _sender(receiver).send(
        "https://hooks.example/x", SECRET, "d1", BODY, public_only=True
    )

    assert not attempt.ok
    assert attempt.status_code == 302
    assert "redirect" in attempt.error
    assert len(receiver.requests) == 1


async def test_a_5xx_is_a_failure_with_its_status():
    receiver = _Receiver(lambda r: httpx.Response(502))

    attempt = await _sender(receiver).send(
        "https://hooks.example/x", SECRET, "d1", BODY, public_only=True
    )

    assert not attempt.ok
    assert (attempt.status_code, attempt.error) == (502, "answered 502")


async def test_no_answer_is_a_failure():
    def hang(request):
        raise httpx.ReadTimeout("slow", request=request)

    attempt = await _sender(_Receiver(hang)).send(
        "https://hooks.example/x", SECRET, "d1", BODY, public_only=True
    )

    assert not attempt.ok
    assert attempt.status_code is None
    assert attempt.error == "no answer within 10 seconds"


async def test_the_cloud_connects_to_the_vetted_address_with_the_host_name():
    receiver = _Receiver(lambda r: httpx.Response(200))

    attempt = await _sender(receiver).send(
        "https://hooks.example/services/x", SECRET, "d1", BODY, public_only=True
    )

    assert attempt.ok
    (request,) = receiver.requests
    assert request.url.host == PUBLIC
    assert request.url.path == "/services/x"
    assert request.headers["host"] == "hooks.example"
    assert request.extensions["sni_hostname"] == "hooks.example"


async def test_the_cloud_rechecks_the_rule_at_send_and_sends_nothing():
    receiver = _Receiver(lambda r: httpx.Response(200))

    attempt = await _sender(receiver, "10.0.0.5").send(
        "https://hooks.example/x", SECRET, "d1", BODY, public_only=True
    )

    assert not attempt.ok
    assert "public internet" in attempt.error
    assert receiver.requests == []
