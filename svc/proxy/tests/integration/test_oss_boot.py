"""what a self-hosted proxy process mounts, and what it refuses to load.

the edition and the analytics switch are read while modules import and the http
app is a module-level singleton, so each case boots a fresh process through
`probe/oss_boot.py` and asserts on what that process reports about itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROBE = Path(__file__).resolve().parents[1] / "probe" / "oss_boot.py"

BILLING_PREFIX = "/api/v1/ee/billing"
ANALYTICS_PREFIXES = ("/api/v1/insight", "/api/v1/event")
ALIAS_PREFIXES = ("/api/v1/ee/insight", "/api/v1/ee/event")


def boot(*, ee: bool = False, analytics: bool) -> dict:
    """boot one proxy process under the given switches and return its report."""
    result = subprocess.run(
        [sys.executable, str(PROBE)],
        capture_output=True,
        text=True,
        # a bare environment: the switches under test are the only ones the
        # process sees, whatever the developer running the suite exports.
        env={
            "PATH": os.environ["PATH"],
            "PROXY_EE_ENABLED": "true" if ee else "false",
            "PROXY_ANALYTICS_ENABLED": "true" if analytics else "false",
            "PROXY_JWT_SECRET_KEY": "probe-jwt-secret",
            "PROXY_TOKEN_SECRET": "probe-token-secret",
        },
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def mounted(routes: list[str], *prefixes: str) -> list[str]:
    return [r for r in routes if r.startswith(prefixes)]


@pytest.fixture(scope="module")
def oss() -> dict:
    return boot(analytics=True)


@pytest.fixture(scope="module")
def oss_without_analytics() -> dict:
    return boot(analytics=False)


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


class TestAnalyticsSwitch:
    def test_on_mounts_insight_and_event(self, oss):
        assert mounted(oss["routes"], *ANALYTICS_PREFIXES)

    def test_on_keeps_the_pre_rename_aliases(self, oss):
        assert mounted(oss["routes"], *ALIAS_PREFIXES)

    def test_off_mounts_nothing_and_leaves_clickhouse_unimported(
        self, oss_without_analytics
    ):
        routes = oss_without_analytics["routes"]

        assert mounted(routes, *ANALYTICS_PREFIXES, *ALIAS_PREFIXES) == []
        assert oss_without_analytics["loaded"] == []
