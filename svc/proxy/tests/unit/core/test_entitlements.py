"""the oss entitlement provider and the edition switch that picks a provider.

UnlimitedEntitlements must answer "no" to every cap. the switch must keep the
cloud plugin off the import path when the edition is oss, and fail at boot —
not at the first request — when the cloud edition is asked for but absent.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from proxysvc import edition
from proxysvc.config import ProxySettings
from proxysvc.core.entitlements import LIMITS
from proxysvc.core.entitlements import UnlimitedEntitlements


class TestUnlimited:
    def test_every_limit_is_unlimited(self):
        limits = UnlimitedEntitlements(frozenset()).limits("free")

        assert limits == dict.fromkeys(LIMITS, -1)

    def test_grants_what_the_deployment_offers_on_any_tier(self):
        entitlements = UnlimitedEntitlements(frozenset({"rbac"}))

        for tier in ("free", "enterprise", "unknown"):
            assert entitlements.features(tier) == {"rbac"}
            assert entitlements.locked_features(tier) == frozenset()

    def test_nothing_to_upgrade_to(self):
        assert UnlimitedEntitlements(frozenset()).upgrade_tiers("insights") == []

    def test_rejects_a_feature_outside_the_catalogue(self):
        with pytest.raises(ValueError, match="no_such_feature"):
            UnlimitedEntitlements(frozenset({"no_such_feature"}))

    async def test_selection_is_free_and_unmetered(self):
        entitlements = UnlimitedEntitlements(frozenset())

        assert await entitlements.on_selection("t-1") is None
        assert await entitlements.usage("t-1") == {}


class TestOfferedFeatures:
    def test_role_changes_are_always_offered(self):
        offered = edition.offered_features(ProxySettings(analytics_enabled=False))

        assert offered == {"rbac"}

    def test_analytics_offers_insights_and_the_event_log(self):
        offered = edition.offered_features(ProxySettings(analytics_enabled=True))

        assert offered == {"rbac", "insights", "event_log"}


class TestEdition:
    def test_oss_is_unlimited_over_what_is_offered(self):
        settings = ProxySettings(ee_enabled=False, analytics_enabled=True)

        entitlements = edition.entitlements(settings, None)

        assert entitlements.edition == "oss"
        assert entitlements.features("free") == edition.offered_features(settings)

    def test_cloud_without_the_plugin_fails_loudly(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "proxysvc.ee", None)

        with pytest.raises(RuntimeError, match="proxysvc.ee package is not installed"):
            edition.entitlements(ProxySettings(ee_enabled=True), None)

    def test_oss_never_imports_the_cloud_plugin(self):
        probe = (
            "import sys\n"
            "from proxysvc.config import ProxySettings\n"
            "from proxysvc import edition\n"
            "import proxysvc.cli, proxysvc.runtime\n"
            "from proxysvc.transport.http.app import app\n"
            "edition.entitlements(ProxySettings(), None)\n"
            "loaded = sorted(m for m in sys.modules\n"
            "    if m.startswith('proxysvc.ee') or m.split('.')[0] == 'stripe')\n"
            "assert not loaded, loaded\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env={"PROXY_EE_ENABLED": "false", "PROXY_ANALYTICS_ENABLED": "true"},
        )

        assert result.returncode == 0, result.stderr
