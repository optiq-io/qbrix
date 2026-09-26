"""unit tests for the feature matrix and require_feature dependency."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import proxysvc.mod.auth.operator as _op_module
from proxysvc import edition
from proxysvc.config import ProxySettings
from proxysvc.mod.auth.model import PlanTier
from proxysvc.ee.plans import FEATURE_MIN_TIER
from proxysvc.ee.plans import TIER_ORDER
from proxysvc.ee.plans import features_for
from proxysvc.ee.plans import has_feature
from proxysvc.transport.http.auth.dependencies import require_feature
from proxysvc.transport.http.exception import PlanTierRequiredException


def _make_user(plan_tier: str):
    user = MagicMock()
    user.id = "u-1"
    user.tenant_id = "t-1"
    user.role = "member"
    user.plan_tier = plan_tier
    user.is_active = True
    return user


# feature -> minimum tier
EXPECTED_MATRIX = {
    "insights": "growth",
    "sso": "scale",
    "rbac": "scale",
    "event_log": "scale",
}


class TestFeatureMatrix:

    def test_matrix_matches_expected(self):
        assert FEATURE_MIN_TIER == EXPECTED_MATRIX

    def test_tier_order_is_complete_and_ascending(self):
        assert TIER_ORDER == ("free", "starter", "growth", "scale", "enterprise")
        assert set(FEATURE_MIN_TIER.values()) <= set(TIER_ORDER)

    @pytest.mark.parametrize("feature,min_tier", EXPECTED_MATRIX.items())
    def test_has_feature_boundaries(self, feature, min_tier):
        min_index = TIER_ORDER.index(min_tier)
        for i, tier in enumerate(TIER_ORDER):
            assert has_feature(tier, feature) is (i >= min_index)

    def test_free_tier_grants_nothing(self):
        assert features_for("free") == []

    def test_enterprise_grants_everything(self):
        assert features_for("enterprise") == sorted(FEATURE_MIN_TIER)

    def test_growth_grants_insights_not_event_log(self):
        granted = features_for("growth")
        assert "insights" in granted
        assert "event_log" not in granted
        assert "rbac" not in granted

    def test_scale_grants_rbac_event_log_sso(self):
        granted = features_for("scale")
        assert "rbac" in granted
        assert "event_log" in granted
        assert "sso" in granted

    def test_unknown_tier_grants_nothing(self):
        assert has_feature("pro", "insights") is False
        assert features_for("pro") == []

    def test_unknown_feature_raises(self):
        with pytest.raises(KeyError):
            has_feature("enterprise", "no_such_feature")

    def test_accepts_plan_tier_enum(self):
        assert has_feature(PlanTier.ENTERPRISE, "event_log") is True
        assert has_feature(PlanTier.FREE, "insights") is False


class TestRequireFeature:
    @pytest.fixture(autouse=True)
    def cloud_operator(self, monkeypatch):
        entitlements = edition.entitlements(
            ProxySettings(ee_enabled=True, analytics_enabled=True), MagicMock()
        )
        monkeypatch.setattr(
            _op_module, "auth_operator", SimpleNamespace(entitlements=entitlements)
        )

    @pytest.mark.parametrize("tier", ["growth", "scale", "enterprise"])
    async def test_allowed_tiers_pass(self, tier):
        dependency = require_feature("insights")
        user = _make_user(tier)

        result = await dependency(user=user)

        assert result is user

    @pytest.mark.parametrize("tier", ["free", "starter"])
    async def test_denied_tiers_raise(self, tier):
        dependency = require_feature("insights")
        user = _make_user(tier)

        with pytest.raises(PlanTierRequiredException) as exc_info:
            await dependency(user=user)

        assert exc_info.value.code == "PLAN_TIER_REQUIRED"
        assert exc_info.value.status_code == 403

    async def test_denied_response_carries_context(self):
        dependency = require_feature("event_log")
        user = _make_user("growth")

        with pytest.raises(PlanTierRequiredException) as exc_info:
            await dependency(user=user)

        body = exc_info.value.to_dict()
        assert body["context"]["feature"] == "event_log"
        assert body["context"]["current_tier"] == "growth"
        assert body["context"]["required_tiers"] == ["scale", "enterprise"]

    def test_unknown_feature_fails_at_registration(self):
        with pytest.raises(KeyError):
            require_feature("no_such_feature")

    async def test_rbac_gated_to_scale(self):
        dependency = require_feature("rbac")

        assert (await dependency(user=_make_user("scale"))) is not None
        with pytest.raises(PlanTierRequiredException):
            await dependency(user=_make_user("growth"))
