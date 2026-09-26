"""unit tests for the tier entitlement matrix."""

from __future__ import annotations

from proxysvc.ee.plans import PAID_TIERS
from proxysvc.ee.plans import PLAN_LIMITS
from proxysvc.ee.plans import limits_for
from proxysvc.mod.auth.scope import ABUSE_RATE_LIMIT_PER_MINUTE

PAID = ["starter", "growth", "scale", "enterprise"]


def test_tiers_are_the_five_expected():
    assert set(PLAN_LIMITS) == {"free", "starter", "growth", "scale", "enterprise"}
    assert "pro" not in PLAN_LIMITS


def test_paid_tiers_matches_matrix():
    assert PAID_TIERS == frozenset(PAID)


def test_every_tier_declares_included_selections():
    for tier, limits in PLAN_LIMITS.items():
        assert "included_selections_per_month" in limits, tier


def test_rate_limit_is_no_longer_tier_derived():
    for limits in PLAN_LIMITS.values():
        assert "rate_limit_per_minute" not in limits
    assert ABUSE_RATE_LIMIT_PER_MINUTE > 0


def test_free_tier_caps():
    free = PLAN_LIMITS["free"]
    assert free["included_selections_per_month"] == 100_000
    assert free["max_api_keys"] == 2
    assert free["max_seats"] == 3
    assert free["max_active_experiments"] == 3


def test_paid_tiers_unlimited_seats_keys_experiments():
    for tier in PAID:
        limits = PLAN_LIMITS[tier]
        assert limits["max_api_keys"] == -1, tier
        assert limits["max_seats"] == -1, tier
        assert limits["max_active_experiments"] == -1, tier


# ── limits_for ────────────────────────────────────────────────────────────────


def test_limits_for_returns_the_tiers_own_row():
    for tier, limits in PLAN_LIMITS.items():
        assert limits_for(tier) == limits, tier


def test_limits_for_unknown_tier_falls_back_to_free():
    assert limits_for("pro") == PLAN_LIMITS["free"]
    assert limits_for("") == PLAN_LIMITS["free"]


def test_limits_for_unlimited_is_minus_one_never_none():
    """clients branch on -1; None or a sentinel would need a second convention."""
    for tier in PAID:
        row = limits_for(tier)
        assert row["max_api_keys"] == -1, tier
        assert None not in row.values(), tier
    assert limits_for("enterprise")["included_selections_per_month"] == -1


def test_limits_for_cannot_mutate_the_matrix():
    """a caller mutating the published row must not rewrite the matrix."""
    row = limits_for("free")
    row["max_api_keys"] = 999
    assert PLAN_LIMITS["free"]["max_api_keys"] == 2
