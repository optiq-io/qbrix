"""the next request path, select and outcome, takes customer frontend traffic,
so it shares the agent surface's abuse limiter, open cors policy and scopes on
both transports."""

from __future__ import annotations

import pytest

from proxysvc.mod.auth.scope import ENDPOINT_SCOPES
from proxysvc.mod.auth.scope import RPC_SCOPES
from proxysvc.transport.grpc.auth.interceptor import RATE_LIMITED_METHODS
from proxysvc.transport.http.auth.middleware import AuthMiddleware
from proxysvc.transport.http.constant import OUTCOME_PATH
from proxysvc.transport.http.constant import SELECT_PATH
from proxysvc.transport.http.cors import AGENT_CORS_PREFIXES

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("path", [SELECT_PATH, OUTCOME_PATH])
def test_http_path_is_limited_and_open_to_browsers(path):
    middleware = AuthMiddleware(app=None)

    assert path in middleware.rate_limited_paths
    assert path in AGENT_CORS_PREFIXES


@pytest.mark.parametrize(
    "path, method, scope",
    [
        (SELECT_PATH, "/qbrix.loop.LoopService/Select", "agent:read"),
        (OUTCOME_PATH, "/qbrix.loop.LoopService/Outcome", "agent:write"),
    ],
)
def test_both_transports_need_the_same_scope(path, method, scope):
    assert ENDPOINT_SCOPES[("POST", path)] == scope
    assert RPC_SCOPES[method] == scope
    assert method in RATE_LIMITED_METHODS
