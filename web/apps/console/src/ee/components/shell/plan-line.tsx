"use client";

import { useAuth } from "@/lib/auth/context";
import { useEntitlements } from "@/lib/entitlements";
import { useSelectionUsage } from "@/ee/lib/billing/hooks";

function compact(n: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
}

// board `Console Shell` / Sidebar / User: "GROWTH · 6.2M / 10M" in mono under
// the name. free and enterprise are undrawn — the document only ever renders
// the growth string — so both follow the drawn pattern: free gets the same
// fraction, enterprise the count alone since its included volume is
// contractual and not a number we hold.
//
// absent entirely outside the cloud edition: the tier still exists but nothing
// enforces it there, so a meter would imply a consequence that does not apply.
export function PlanLine() {
  const { user } = useAuth();
  const { isCloud } = useEntitlements();
  const { data: usage } = useSelectionUsage();

  if (!isCloud || !user?.plan_tier) return null;

  const label = user.plan_tier.toUpperCase();
  let text = label;
  if (usage) {
    text =
      usage.included === null
        ? `${label} · ${compact(usage.used)}`
        : `${label} · ${compact(usage.used)} / ${compact(usage.included)}`;
  }

  return (
    <span className="truncate font-mono text-[11px] tracking-[0.02em] text-text-faint">
      {text}
    </span>
  );
}
