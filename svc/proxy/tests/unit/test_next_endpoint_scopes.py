"""a key carries the scopes it was created with, and the auth middleware checks
them by path, so every next route must resolve to its scope there too."""

from __future__ import annotations

import pytest

from proxysvc.transport.http.auth.middleware import AuthMiddleware

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "method, path, scope",
    [
        ("GET", "/api/v1/loops", "loop:read"),
        ("GET", "/api/v1/loops/checkout-headline", "loop:read"),
        ("GET", "/api/v1/loops/checkout-headline/cycles", "loop:read"),
        ("GET", "/api/v1/loops/checkout-headline/history", "loop:read"),
        ("GET", "/api/v1/loops/checkout-headline/results", "loop:read"),
        ("POST", "/api/v1/loops", "loop:write"),
        ("POST", "/api/v1/loops/checkout-headline/launch", "loop:write"),
        ("POST", "/api/v1/loops/checkout-headline/resume", "loop:write"),
        ("PATCH", "/api/v1/loops/checkout-headline", "loop:write"),
        ("GET", "/api/v1/metrics", "metric:read"),
        ("GET", "/api/v1/metrics/purchase", "metric:read"),
        ("POST", "/api/v1/metrics", "metric:write"),
    ],
)
def test_resolves_to_its_scope(method, path, scope):
    assert AuthMiddleware._get_required_scope_for_path(method, path) == scope


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/v1/pins"),
        ("PUT", "/api/v1/pins/loop/abc"),
        ("DELETE", "/api/v1/pins/metric/abc"),
    ],
)
def test_pinning_needs_no_scope(method, path):
    """a pin is a person's own navigation, so a viewer's role reaches it too."""
    assert AuthMiddleware._get_required_scope_for_path(method, path) is None


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/v1/connections"),
        ("DELETE", "/api/v1/connections/abc"),
        ("GET", "/api/v1/connections/requests/abc"),
        ("POST", "/api/v1/connections/requests/abc"),
    ],
)
def test_signing_in_needs_no_scope(method, path):
    """any role, a viewer's included, signs its own clients in and manages them."""
    assert AuthMiddleware._get_required_scope_for_path(method, path) is None
