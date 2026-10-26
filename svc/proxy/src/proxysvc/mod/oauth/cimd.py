from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from collections.abc import Awaitable
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import httpx
from cachebox import TTLCache

from proxysvc.core.error import OAuthError
from proxysvc.mod.oauth.client import ClientIdentity
from proxysvc.mod.oauth.client import documented_client

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 5.0
MAX_BYTES = 64 * 1024
CACHE_TTL_SEC = 3600

Resolver = Callable[[str], Awaitable[list[str]]]


def is_document_url(client_id: str) -> bool:
    """a client_id that is an https url names a client metadata document."""
    return client_id.startswith("https://")


async def resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, 443, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(info[4][0] for info in infos))


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


def _refused(description: str) -> OAuthError:
    return OAuthError("invalid_client", description)


class CIMDFetcher:
    """fetches client metadata documents without becoming a probe into the
    network qbrix runs in.

    the host is resolved once and every address checked before connecting;
    the request then goes to that vetted address, with the host only in the
    Host header and tls server name, so a second dns answer can't redirect it
    inward. redirects are refused, proxies from the environment ignored, and
    the body capped.
    """

    def __init__(
        self,
        *,
        resolver: Resolver = resolve,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._resolver = resolver
        self._transport = transport
        self._cache: TTLCache = TTLCache(maxsize=1000, ttl=CACHE_TTL_SEC)

    async def client(self, url: str) -> ClientIdentity:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        client = documented_client(url, await self._fetch(url))
        self._cache[url] = client
        return client

    async def _fetch(self, url: str) -> dict:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.port not in (None, 443)
            or parts.username
            or parts.password
        ):
            raise _refused("a client_id url must be https on the default port")
        host = parts.hostname
        try:
            addresses = await self._resolver(host)
        except OSError as e:
            raise _refused(f"the client's host {host} doesn't resolve") from e
        if not addresses or not all(_public(a) for a in addresses):
            raise _refused(f"the client's host {host} isn't on the public internet")

        address = addresses[0]
        netloc = f"[{address}]" if ":" in address else address
        target = urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=TIMEOUT_SEC,
                follow_redirects=False,
                trust_env=False,
            ) as http:
                async with http.stream(
                    "GET",
                    target,
                    headers={"Host": host, "Accept": "application/json"},
                    extensions={"sni_hostname": host},
                ) as response:
                    if response.status_code != 200:
                        raise _refused(
                            f"the client's metadata document answered "
                            f"{response.status_code}"
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise _refused(
                                "the client's metadata document is larger than 64 KB"
                            )
        except httpx.TimeoutException as e:
            raise _refused("the client's metadata document took too long") from e
        except httpx.HTTPError as e:
            logger.info(f"client metadata fetch failed for {url}: {e}")
            raise _refused("the client's metadata document couldn't be fetched") from e
        try:
            document = json.loads(body)
        except ValueError as e:
            raise _refused("the client's metadata document isn't json") from e
        if not isinstance(document, dict):
            raise _refused("the client's metadata document isn't a json object")
        return document
