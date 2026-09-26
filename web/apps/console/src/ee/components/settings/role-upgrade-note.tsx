"use client";

import { useEntitlements } from "@/lib/entitlements";
import { FEATURE_MIN_TIER, planLabel } from "@/ee/lib/billing/plans";

// the members tab itself is never tier-gated — every workspace needs to see who
// is in it. only role *assignment* is, so this note sits under the list rather
// than replacing it, and renders nothing unless the tier is what withholds it.
export function RoleUpgradeNote() {
  const { gate } = useEntitlements();
  if (gate("rbac") !== "locked") return null;

  return (
    <p className="border-b border-border-subtle px-7 py-4 text-[13.5px] text-text-faint">
      Changing a member&apos;s role is included on the{" "}
      {planLabel(FEATURE_MIN_TIER.rbac)} plan. Everything else here works on
      your current plan.
    </p>
  );
}
