from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")


def host_of(origin: str) -> str:
    return urlsplit(origin).netloc or origin


def unreachable_reason(origin: str) -> str | None:
    """why github can't send events to this address, or None when nothing
    about the address itself rules it out."""
    parts = urlsplit(origin)
    host = (parts.hostname or "").lower()
    where = host_of(origin)
    if parts.scheme != "https":
        return (
            f"GitHub can't reach {where}: it isn't an https address. "
            "Set PROXY_PUBLIC_URL to a public https address, such as a tunnel's."
        )
    if _is_private(host):
        return (
            f"GitHub can't reach {where}: it is a private address. "
            "Set PROXY_PUBLIC_URL to a public https address, such as a tunnel's."
        )
    return None


def _is_private(host: str) -> bool:
    if not host or host == "localhost" or host.endswith(PRIVATE_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host
    return not address.is_global
