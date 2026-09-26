from __future__ import annotations

from typing import Literal
from typing import Protocol

Edition = Literal["oss", "cloud"]

FEATURES = frozenset({"insights", "event_log", "rbac", "sso"})

LIMITS = (
    "included_selections_per_month",
    "max_api_keys",
    "max_seats",
    "max_active_experiments",
)


class Entitlements(Protocol):
    """what a tenant may do, keyed on the tier its principal already carries.

    core reads limits, features and the selection quota only through this, so
    which edition is running is decided in one place (proxysvc.edition). a
    limit of -1 is unlimited.
    """

    edition: Edition

    def limits(self, tier: str) -> dict[str, int]: ...

    def features(self, tier: str) -> frozenset[str]: ...

    def locked_features(self, tier: str) -> frozenset[str]:
        """features this deployment sells but the tier does not include."""
        ...

    def upgrade_tiers(self, feature: str) -> list[str]:
        """the tiers that would grant a feature, in upgrade order."""
        ...

    async def on_selection(self, tenant_id: str) -> None:
        """count one selection; raises UsageLimitError to reject it."""
        ...

    async def usage(self, tenant_id: str) -> dict[str, float]:
        """the current period's metered usage, {} when nothing is metered."""
        ...

    def invalidate(self, tenant_id: str) -> None: ...


class UnlimitedEntitlements:
    """self-hosted: no caps, no quota, every feature the deployment offers."""

    edition: Edition = "oss"

    def __init__(self, features: frozenset[str]):
        unknown = features - FEATURES
        if unknown:
            raise ValueError(f"unknown features: {sorted(unknown)}")
        self._features = features

    def limits(self, tier: str) -> dict[str, int]:
        return dict.fromkeys(LIMITS, -1)

    def features(self, tier: str) -> frozenset[str]:
        return self._features

    def locked_features(self, tier: str) -> frozenset[str]:
        return frozenset()

    def upgrade_tiers(self, feature: str) -> list[str]:
        return []

    async def on_selection(self, tenant_id: str) -> None:
        return None

    async def usage(self, tenant_id: str) -> dict[str, float]:
        return {}

    def invalidate(self, tenant_id: str) -> None:
        return None
