"""unit tests for the http-layer auth utilities (client ip, bucket lookup)."""

from __future__ import annotations

from types import SimpleNamespace

from proxysvc.transport.http.auth import constant, util


def _req(headers: dict | None = None, client_host: str | None = "127.0.0.1"):
    """minimal stand-in for a starlette Request.

    client_ip() reads request.headers.get(...) with lowercase keys and
    request.client.host, which this stub satisfies.
    """
    client = SimpleNamespace(host=client_host) if client_host is not None else None
    return SimpleNamespace(headers=headers or {}, client=client)


class TestStripPort:

    def test_ipv4_with_port(self):
        assert util._strip_port("203.0.113.7:443") == "203.0.113.7"

    def test_ipv6_with_port(self):
        assert util._strip_port("2001:db8::1:443") == "2001:db8::1"

    def test_ipv4_without_port_unchanged(self):
        assert util._strip_port("203.0.113.7") == "203.0.113.7"


class TestIpBucketFor:

    def test_known_auth_paths(self):
        assert util.ip_bucket_for("/api/auth/login") == (
            "login",
            constant.LOGIN_IP_PER_MIN,
        )
        assert util.ip_bucket_for("/api/auth/forgot-password") == (
            "forgot",
            constant.FORGOT_IP_PER_MIN,
        )
        assert util.ip_bucket_for("/api/auth/verify-email") == (
            "verify_email",
            constant.VERIFY_EMAIL_IP_PER_MIN,
        )
        assert util.ip_bucket_for("/api/auth/resend-verification") == (
            "resend_verification",
            constant.RESEND_VERIFICATION_IP_PER_MIN,
        )

    def test_unknown_path_returns_none(self):
        assert util.ip_bucket_for("/api/v1/pools") is None
        assert util.ip_bucket_for("/api/auth/profile") is None


class TestClientIpSingleHop:
    """self-host: one ingress or gateway appends the client to x-forwarded-for."""

    def _ip(self, req) -> str:
        return util.client_ip(req, trusted_hops=1, trust_cloudfront_header=False)

    def test_rightmost_xff_entry_is_the_client(self):
        req = _req(headers={"x-forwarded-for": "203.0.113.7"}, client_host="10.0.0.1")
        assert self._ip(req) == "203.0.113.7"

    def test_spoofed_leftmost_entries_are_ignored(self):
        req = _req(
            headers={"x-forwarded-for": "6.6.6.6, 7.7.7.7, 203.0.113.7"},
            client_host="10.0.0.1",
        )
        assert self._ip(req) == "203.0.113.7"

    def test_cloudfront_header_is_ignored(self):
        req = _req(
            headers={
                "cloudfront-viewer-address": "6.6.6.6:443",
                "x-forwarded-for": "203.0.113.7",
            },
            client_host="10.0.0.1",
        )
        assert self._ip(req) == "203.0.113.7"

    def test_cloudfront_header_alone_falls_back_to_peer(self):
        req = _req(
            headers={"cloudfront-viewer-address": "6.6.6.6:443"},
            client_host="10.0.0.1",
        )
        assert self._ip(req) == "10.0.0.1"

    def test_distinct_clients_get_distinct_keys(self):
        a = _req(headers={"x-forwarded-for": "203.0.113.7"}, client_host="10.0.0.1")
        b = _req(headers={"x-forwarded-for": "198.51.100.9"}, client_host="10.0.0.1")
        assert self._ip(a) != self._ip(b)


class TestClientIpCloudfront:
    """cloud: cloudfront → alb → pod."""

    def test_trusted_header_wins_over_xff(self):
        req = _req(
            headers={
                "cloudfront-viewer-address": "203.0.113.7:51234",
                "x-forwarded-for": "1.1.1.1, 2.2.2.2",
            }
        )
        assert (
            util.client_ip(req, trusted_hops=2, trust_cloudfront_header=True)
            == "203.0.113.7"
        )

    def test_xff_counts_two_hops_from_the_right(self):
        req = _req(headers={"x-forwarded-for": "6.6.6.6, 203.0.113.7, 70.41.3.18"})
        assert (
            util.client_ip(req, trusted_hops=2, trust_cloudfront_header=False)
            == "203.0.113.7"
        )

    def test_fewer_entries_than_hops_falls_back_to_peer(self):
        req = _req(headers={"x-forwarded-for": "203.0.113.7"}, client_host="10.0.0.1")
        assert (
            util.client_ip(req, trusted_hops=2, trust_cloudfront_header=False)
            == "10.0.0.1"
        )


class TestClientIpFallbacks:

    def test_zero_hops_ignores_xff(self):
        req = _req(
            headers={"x-forwarded-for": "203.0.113.7, 70.41.3.18"},
            client_host="10.0.0.1",
        )
        assert (
            util.client_ip(req, trusted_hops=0, trust_cloudfront_header=False)
            == "10.0.0.1"
        )

    def test_no_headers_uses_peer(self):
        req = _req(headers={}, client_host="10.0.0.5")
        assert (
            util.client_ip(req, trusted_hops=1, trust_cloudfront_header=False)
            == "10.0.0.5"
        )

    def test_no_client_returns_unknown(self):
        req = _req(headers={}, client_host=None)
        assert (
            util.client_ip(req, trusted_hops=1, trust_cloudfront_header=False)
            == "unknown"
        )
