from __future__ import annotations

from typing import Optional

from fastapi import Request

from proxysvc.transport.http.auth.constant import IP_BUCKETS


def ip_bucket_for(path: str) -> Optional[tuple[str, int]]:
    """return (scope, ip_limit) for an auth endpoint path, or None."""
    return IP_BUCKETS.get(path)


def _strip_port(addr: str) -> str:
    """strip a trailing :port from an ip:port string, handling ipv6.

    cloudfront's CloudFront-Viewer-Address is "ip:port". an ipv4 value has a
    single colon; an ipv6 value has many, so only strip when the part after the
    last colon is numeric.
    """
    head, sep, tail = addr.rpartition(":")
    if sep and tail.isdigit():
        return head
    return addr


def client_ip(
    request: Request, trusted_hops: int, trust_cloudfront_header: bool
) -> str:
    """extract the real client ip in a spoof-resistant way.

    order of preference:
      1. CloudFront-Viewer-Address, only when `trust_cloudfront_header` is set.
         cloudfront overwrites it, but without cloudfront in front any client
         can send it, so it is ignored unless the deployment says otherwise.
      2. x-forwarded-for, counting `trusted_hops` entries from the RIGHT. each
         trusted proxy appends the address it received the connection from, so
         the rightmost `trusted_hops` entries are trustworthy and everything to
         their left is client-controlled. counting from the right prevents an
         attacker from rotating a spoofed leftmost value to evade the limiter.
      3. the immediate peer (request.client.host).
    """
    if trust_cloudfront_header:
        cf_addr = request.headers.get("cloudfront-viewer-address")
        if cf_addr:
            return _strip_port(cf_addr.strip())

    xff = request.headers.get("x-forwarded-for")
    if xff and trusted_hops > 0:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= trusted_hops:
            return parts[-trusted_hops]

    if request.client and request.client.host:
        return request.client.host

    return "unknown"
