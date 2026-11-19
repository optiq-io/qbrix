from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable
from collections.abc import Callable
from urllib.parse import SplitResult
from urllib.parse import urlunsplit

Resolver = Callable[[str], Awaitable[list[str]]]


class HostUnresolvedError(Exception):
    """the host has no address."""


class HostNotPublicError(Exception):
    """at least one of the host's addresses isn't on the public internet."""


async def resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, 443, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(info[4][0] for info in infos))


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


async def public_address(host: str, resolver: Resolver) -> str:
    """resolve the host once and vouch for every address it has, so a request
    sent to the returned address can't be turned inward by a second answer."""
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = await resolver(host)
        except OSError as e:
            raise HostUnresolvedError(host) from e
    if not addresses:
        raise HostUnresolvedError(host)
    if not all(is_public(a) for a in addresses):
        raise HostNotPublicError(host)
    return addresses[0]


def pinned_target(parts: SplitResult, address: str) -> str:
    """the url with its host replaced by the vetted address; the host itself
    goes in the Host header and the tls server name."""
    netloc = f"[{address}]" if ":" in address else address
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
