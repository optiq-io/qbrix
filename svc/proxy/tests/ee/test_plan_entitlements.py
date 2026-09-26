"""the cloud entitlement provider answers exactly what the tier matrix answers.

cloud behaviour is not allowed to move when it is reached through the edition
extension rather than named directly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from proxysvc import edition
from proxysvc.config import ProxySettings
from proxysvc.core.entitlements import FEATURES
from proxysvc.core.entitlements import LIMITS
from proxysvc.ee.entitlements import PlanEntitlements
from proxysvc.ee.metering.model import UsageContext
from proxysvc.ee.plans import FEATURE_MIN_TIER
from proxysvc.ee.plans import PLAN_LIMITS
from proxysvc.ee.plans import TIER_ORDER

CLOUD = ProxySettings(ee_enabled=True, analytics_enabled=True)


def _plan(redis=None, settings: ProxySettings = CLOUD) -> PlanEntitlements:
    return edition.entitlements(settings, redis or MagicMock())


class TestPlan:
    def test_the_catalogue_is_the_tier_matrix(self):
        assert FEATURES == frozenset(FEATURE_MIN_TIER)

    def test_limit_rows_have_the_catalogue_keys(self):
        for row in PLAN_LIMITS.values():
            assert tuple(row) == LIMITS

    def test_cloud_with_analytics_offers_the_whole_catalogue(self):
        assert _plan().locked_features("free") == FEATURES

    @pytest.mark.parametrize("tier", TIER_ORDER)
    def test_granted_and_locked_partition_the_catalogue(self, tier):
        entitlements = _plan()
        granted = entitlements.features(tier)
        locked = entitlements.locked_features(tier)

        assert granted | locked == FEATURES
        assert not granted & locked

    @pytest.mark.parametrize("tier", TIER_ORDER)
    def test_limits_are_the_tiers_row(self, tier):
        assert _plan().limits(tier) == PLAN_LIMITS[tier]

    def test_what_is_not_deployed_is_neither_granted_nor_sold(self):
        entitlements = _plan(
            settings=ProxySettings(ee_enabled=True, analytics_enabled=False)
        )

        for tier in TIER_ORDER:
            assert not entitlements.features(tier) & {"insights", "event_log"}
            assert not entitlements.locked_features(tier) & {"insights", "event_log"}

    def test_upgrade_tiers_are_the_granting_tiers_in_order(self):
        assert _plan().upgrade_tiers("insights") == ["growth", "scale", "enterprise"]
        assert _plan().upgrade_tiers("rbac") == ["scale", "enterprise"]

    async def test_usage_reads_the_period_counter(self):
        redis = MagicMock()
        redis.get_selection_usage = AsyncMock(return_value=42)
        entitlements = _plan(redis)
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        end = datetime(2026, 10, 1, tzinfo=timezone.utc)
        entitlements._resolver.resolve = AsyncMock(
            return_value=UsageContext(
                tenant_id="t-1",
                tier="free",
                included=100_000,
                period_key="2026-09",
                period_start=start,
                period_end=end,
            )
        )

        usage = await entitlements.usage("t-1")

        redis.get_selection_usage.assert_awaited_once_with("t-1", "2026-09")
        assert usage == {
            "selections_this_period": 42,
            "period_start": start.timestamp(),
            "period_end": end.timestamp(),
        }

    def test_invalidate_drops_the_resolved_tier(self):
        entitlements = _plan()
        entitlements._resolver.invalidate = MagicMock()

        entitlements.invalidate("t-1")

        entitlements._resolver.invalidate.assert_called_once_with("t-1")


class TestEdition:
    def test_cloud_is_the_plan(self):
        entitlements = _plan()

        assert isinstance(entitlements, PlanEntitlements)
        assert entitlements.edition == "cloud"

    def test_resolving_entitlements_does_not_import_the_http_auth_layer(self):
        """the runtime resolves entitlements while building ProxyService, before
        init_operators(), so the plugin must not drag the http auth layer in on
        that path."""
        probe = (
            "import sys\n"
            "from unittest.mock import MagicMock\n"
            "from proxysvc import edition\n"
            "from proxysvc.config import settings\n"
            "edition.entitlements(settings, MagicMock())\n"
            "assert 'proxysvc.transport.http.auth.dependencies' not in sys.modules\n"
            "assert 'proxysvc.transport.http.auth.middleware' not in sys.modules\n"
        )
        env = {
            **os.environ,
            "PROXY_EE_ENABLED": "true",
            "PROXY_ANALYTICS_ENABLED": "true",
        }
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, env=env
        )

        assert result.returncode == 0, result.stderr
