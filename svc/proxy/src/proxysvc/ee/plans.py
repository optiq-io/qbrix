"""plan tiers: what each tier includes and which features it unlocks."""

PLAN_LIMITS = {
    "free": {
        "included_selections_per_month": 100_000,
        "max_api_keys": 2,
        "max_seats": 3,
        "max_active_experiments": 3,
    },
    "starter": {
        "included_selections_per_month": 1_000_000,
        "max_api_keys": -1,
        "max_seats": -1,
        "max_active_experiments": -1,
    },
    "growth": {
        "included_selections_per_month": 10_000_000,
        "max_api_keys": -1,
        "max_seats": -1,
        "max_active_experiments": -1,
    },
    "scale": {
        "included_selections_per_month": 50_000_000,
        "max_api_keys": -1,
        "max_seats": -1,
        "max_active_experiments": -1,
    },
    "enterprise": {
        "included_selections_per_month": -1,
        "max_api_keys": -1,
        "max_seats": -1,
        "max_active_experiments": -1,
    },
}


PAID_TIERS = frozenset({"starter", "growth", "scale", "enterprise"})

TIER_ORDER = ("free", "starter", "growth", "scale", "enterprise")

CLOUD_FEATURES = frozenset({"sso"})

FEATURE_MIN_TIER = {
    "insights": "growth",
    "sso": "scale",
    "rbac": "scale",
    "event_log": "scale",
}


def has_feature(tier: str, feature: str) -> bool:
    """whether a plan tier grants a feature.

    unknown tiers grant nothing; unknown features raise so typos in gate
    wiring fail loudly instead of silently denying.
    """
    # membership/index use equality, so str-enum tiers (PlanTier) work as-is
    min_tier = FEATURE_MIN_TIER[feature]
    if tier not in TIER_ORDER:
        return False
    return TIER_ORDER.index(tier) >= TIER_ORDER.index(min_tier)


def features_for(tier: str) -> list[str]:
    """sorted list of features granted to a plan tier."""
    return sorted(f for f in FEATURE_MIN_TIER if has_feature(tier, f))


def limits_for(tier: str) -> dict[str, int]:
    """a copy of the tier's limit row, safe to publish. -1 is unlimited."""
    return dict(PLAN_LIMITS.get(tier, PLAN_LIMITS["free"]))
