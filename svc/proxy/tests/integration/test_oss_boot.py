"""what a self-hosted proxy process mounts, and what it refuses to load.

the edition and the next switch are read while modules import and the http
app is a module-level singleton, so each case boots a fresh process through
`probe/oss_boot.py` and asserts on what that process reports about itself.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

PROBE = Path(__file__).resolve().parents[1] / "probe" / "oss_boot.py"

BILLING_PREFIX = "/api/v1/ee/billing"

# today's product, with next off. a route or grpc service that appears here
# without a deliberate edit was mounted outside proxysvc/next.py.
TODAY_ROUTES = frozenset(
    {
        "/api/auth/account",
        "/api/auth/api-keys",
        "/api/auth/api-keys/{api_key_id}",
        "/api/auth/api-keys/{api_key_id}/rotate",
        "/api/auth/api-keys/{api_key_id}/usage",
        "/api/auth/change-password",
        "/api/auth/config",
        "/api/auth/forgot-password",
        "/api/auth/invites/{token}",
        "/api/auth/invites/{token}/accept",
        "/api/auth/login",
        "/api/auth/profile",
        "/api/auth/refresh",
        "/api/auth/register",
        "/api/auth/resend-verification",
        "/api/auth/reset-password",
        "/api/auth/roles",
        "/api/auth/users",
        "/api/auth/users/stats",
        "/api/auth/users/{user_id}/role",
        "/api/auth/users/{user_id}/status",
        "/api/auth/verify-email",
        "/api/auth/workspace",
        "/api/auth/workspace/invites",
        "/api/auth/workspace/invites/{invite_id}",
        "/api/auth/workspace/members",
        "/api/health",
        "/api/v1/agent/feedback",
        "/api/v1/agent/select",
        "/api/v1/event",
        "/api/v1/event/audit",
        "/api/v1/event/experiment/{experiment_id}/activity",
        "/api/v1/event/feedback",
        "/api/v1/event/selection",
        "/api/v1/event/selection/{request_id}",
        "/api/v1/experiments",
        "/api/v1/experiments/{experiment_id}",
        "/api/v1/experiments/{experiment_id}/reset",
        "/api/v1/gates/{experiment_id}",
        "/api/v1/gates/{experiment_id}/evaluate",
        "/api/v1/insight/experiment/{experiment_id}",
        "/api/v1/insight/experiment/{experiment_id}/arms",
        "/api/v1/insight/experiment/{experiment_id}/cumulative",
        "/api/v1/insight/experiment/{experiment_id}/funnel",
        "/api/v1/insight/experiment/{experiment_id}/timeseries",
        "/api/v1/insight/experiment/{experiment_id}/timeseries/arms",
        "/api/v1/insight/experiment/{experiment_id}/timeseries/rewards",
        "/api/v1/insight/workspace/arms",
        "/api/v1/policies",
        "/api/v1/pools",
        "/api/v1/pools/{pool_id}",
        "/api/v1/pools/{pool_id}/experiments",
        "/api/v1/runtime/cortex/health",
        "/api/v1/runtime/motor/health",
        "/api/v1/runtime/redis/health",
        "/api/v1/runtime/redis/stream/size",
        "/health",
        "/info",
    }
)

TODAY_GRPC_SERVICES = frozenset(
    {
        "grpc.reflection.v1alpha.ServerReflection",
        "qbrix.auth.AuthService",
        "qbrix.proxy.ProxyService",
    }
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_probe(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROBE)],
        capture_output=True,
        text=True,
        # a bare environment: the switches under test are the only ones the
        # process sees, whatever the developer running the suite exports.
        env={
            "PATH": os.environ["PATH"],
            "PROXY_GRPC_HOST": "127.0.0.1",
            "PROXY_GRPC_PORT": str(free_port()),
            "PROXY_JWT_SECRET_KEY": "probe-jwt-secret",
            "PROXY_TOKEN_SECRET": "probe-token-secret",
            **env,
        },
    )


def boot(*, ee: bool = False, next_: bool = False) -> dict:
    """boot one proxy process under the given switches and return its report."""
    result = run_probe(
        {
            "PROXY_EE_ENABLED": "true" if ee else "false",
            "PROXY_NEXT_ENABLED": "true" if next_ else "false",
            "PROXY_CLICKHOUSE_HOST": "localhost",
        }
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def mounted(routes: list[str], *prefixes: str) -> list[str]:
    return [r for r in routes if r.startswith(prefixes)]


@pytest.fixture(scope="module")
def oss() -> dict:
    return boot()


@pytest.fixture(scope="module")
def oss_with_next() -> dict:
    return boot(next_=True)


class TestBoot:
    def test_the_process_starts_and_stops(self, oss):
        assert "/health" in oss["routes"]
        assert "/api/v1/agent/select" in oss["routes"]


class TestCloudPluginStaysOut:
    def test_neither_the_plugin_nor_stripe_is_imported(self, oss):
        assert "proxysvc.ee" not in oss["loaded"]
        assert "stripe" not in oss["loaded"]

    def test_no_billing_route_is_mounted(self, oss):
        assert mounted(oss["routes"], BILLING_PREFIX) == []


class TestClickhouseIsRequired:
    def test_boot_refuses_a_missing_host_and_names_it(self):
        result = run_probe({"PROXY_EE_ENABLED": "false"})

        assert result.returncode != 0
        assert "PROXY_CLICKHOUSE_HOST must be set" in result.stderr


class TestNextSwitch:
    def test_off_mounts_exactly_todays_routes(self, oss):
        assert set(oss["routes"]) == TODAY_ROUTES

    def test_off_serves_exactly_todays_grpc_services(self, oss):
        assert set(oss["grpc_services"]) == TODAY_GRPC_SERVICES

    def test_on_keeps_todays_surface(self, oss_with_next):
        assert set(oss_with_next["routes"]) >= TODAY_ROUTES
        assert set(oss_with_next["grpc_services"]) >= TODAY_GRPC_SERVICES

    def test_on_mounts_the_next_routes(self, oss_with_next):
        assert set(oss_with_next["routes"]) - TODAY_ROUTES == {
            "/api/v1/metrics",
            "/api/v1/metrics/{metric}",
            "/api/v1/loops",
            "/api/v1/loops/{loop}",
            "/api/v1/loops/{loop}/launch",
            "/api/v1/loops/{loop}/resume",
            "/api/v1/loops/{loop}/cycles",
            "/api/v1/loops/{loop}/history",
            "/api/v1/loops/{loop}/results",
            "/api/v1/select",
            "/api/v1/outcome",
            "/api/v1/connections",
            "/api/v1/connections/{connection_id}",
            "/api/oauth/requests/{request_id}",
            "/.well-known/oauth-authorization-server",
            "/oauth/register",
            "/oauth/authorize",
            "/oauth/token",
            "/oauth/revoke",
        }

    def test_on_mounts_the_next_grpc_services(self, oss_with_next):
        assert set(oss_with_next["grpc_services"]) - TODAY_GRPC_SERVICES == {
            "qbrix.loop.LoopService",
        }
