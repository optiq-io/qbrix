from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from importlib.metadata import version

import httpx

from proxysvc.core.error import WebhookURLError
from proxysvc.core.outbound import Resolver
from proxysvc.core.outbound import resolve
from proxysvc.mod.webhook import signature
from proxysvc.mod.webhook.rule import Route
from proxysvc.mod.webhook.rule import route

TIMEOUT_SEC = 10.0
DELIVERY_HEADER = "qbrix-delivery"


@dataclass(frozen=True, slots=True)
class Attempt:
    """one try at a delivery: the status the receiver answered, or why there
    was no answer to count."""

    at: datetime
    status_code: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None

    def to_dict(self) -> dict:
        return {
            "at": self.at.isoformat(),
            "status_code": self.status_code,
            "error": self.error,
        }


def encode(body: dict) -> bytes:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()


class WebhookSender:
    """posts one signed message to a webhook and reports what came back.

    the url is checked against the edition's rule before every send, not
    only on save, because what a host resolves to can change. redirects are
    a failure, never followed, proxies from the environment are ignored, and
    the receiver's body is never read.
    """

    def __init__(
        self,
        *,
        resolver: Resolver = resolve,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._resolver = resolver
        self._transport = transport
        self._clock = clock
        self._user_agent = f"qbrix/{version('proxysvc')}"

    async def check(self, url: str, *, public_only: bool) -> Route:
        """raises WebhookURLError when the url breaks the edition's rule."""
        return await route(url, public_only=public_only, resolver=self._resolver)

    async def send(
        self,
        url: str,
        secret: str,
        delivery_id: str,
        body: dict,
        *,
        public_only: bool,
    ) -> Attempt:
        now = self._clock()
        at = datetime.fromtimestamp(now, timezone.utc)
        try:
            where = await self.check(url, public_only=public_only)
        except WebhookURLError as e:
            return Attempt(at=at, error=str(e))

        raw = encode(body)
        headers = {
            signature.HEADER: signature.sign(secret, int(now), raw),
            DELIVERY_HEADER: delivery_id,
            "content-type": "application/json",
            "user-agent": self._user_agent,
        }
        extensions = {}
        if where.host is not None:
            headers["host"] = where.host
            extensions["sni_hostname"] = where.host
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=TIMEOUT_SEC,
                follow_redirects=False,
                trust_env=False,
            ) as http:
                response = await http.post(
                    where.target, content=raw, headers=headers, extensions=extensions
                )
        except httpx.TimeoutException:
            return Attempt(at=at, error="no answer within 10 seconds")
        except httpx.HTTPError:
            return Attempt(at=at, error="couldn't connect")
        if response.is_redirect:
            return Attempt(
                at=at,
                status_code=response.status_code,
                error="answered with a redirect, which qbrix doesn't follow",
            )
        if not response.is_success:
            return Attempt(
                at=at,
                status_code=response.status_code,
                error=f"answered {response.status_code}",
            )
        return Attempt(at=at, status_code=response.status_code)
