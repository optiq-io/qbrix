from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from proxysvc.core.error import WebhookURLError
from proxysvc.core.outbound import HostNotPublicError
from proxysvc.core.outbound import HostUnresolvedError
from proxysvc.core.outbound import Resolver
from proxysvc.core.outbound import pinned_target
from proxysvc.core.outbound import public_address

MAX_URL_LENGTH = 2048


@dataclass(frozen=True, slots=True)
class Route:
    """where a delivery connects: the url itself, or in the cloud the vetted
    address, with the host carried in the Host header and tls server name."""

    target: str
    host: str | None = None


async def route(url: str, *, public_only: bool, resolver: Resolver) -> Route:
    """check a webhook url against the edition's rule and say where to send.

    a self-hosted install may post to any http(s) address, its own network
    included. the cloud posts only over https to public addresses, so one
    workspace can't make qbrix reach into the network it runs in.
    """
    if len(url) > MAX_URL_LENGTH:
        raise WebhookURLError("the webhook's address is longer than 2048 characters")
    try:
        parts = urlsplit(url)
        parts.port  # raises on a malformed port
    except ValueError as e:
        raise WebhookURLError("the webhook's address isn't a valid url") from e
    allowed = ("https",) if public_only else ("http", "https")
    if parts.scheme not in allowed or not parts.hostname:
        raise WebhookURLError(
            "the webhook needs an https address"
            if public_only
            else "the webhook needs an http or https address"
        )
    if parts.username or parts.password:
        raise WebhookURLError(
            "the webhook's address can't carry a user name or password"
        )
    if not public_only:
        return Route(target=url)

    host = parts.hostname
    try:
        address = await public_address(host, resolver)
    except HostUnresolvedError as e:
        raise WebhookURLError(f"the webhook's host {host} doesn't resolve") from e
    except HostNotPublicError as e:
        raise WebhookURLError(
            f"the webhook's host {host} isn't on the public internet"
        ) from e
    return Route(target=pinned_target(parts, address), host=host)


def masked(url: str) -> str:
    """the url up to its host: a Slack link's path is its credential."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"
    return f"{origin}/…" if (parts.path not in ("", "/") or parts.query) else origin
