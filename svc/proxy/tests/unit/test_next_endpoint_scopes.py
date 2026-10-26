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
        ("GET", "/api/v1/metrics", "metric:read"),
        ("GET", "/api/v1/metrics/purchase", "metric:read"),
        ("POST", "/api/v1/metrics", "metric:write"),
    ],
)
def test_resolves_to_its_scope(method, path, scope):
    assert AuthMiddleware._get_required_scope_for_path(method, path) == scope
