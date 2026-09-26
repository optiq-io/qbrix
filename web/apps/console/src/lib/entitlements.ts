"use client";

import { useCallback } from "react";
import { notFound } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import type { Edition } from "@/lib/api/types";

// mirrors FEATURES in svc/proxy/src/proxysvc/core/entitlements.py
export type Feature = "insights" | "event_log" | "rbac" | "sso";

// the backend answers all three states, and the two closed ones differ:
//
//   locked → the deployment sells the feature and this tenant's tier does not
//            include it. render the upgrade prompt.
//   absent → the deployment does not offer it at all — analytics is not
//            deployed, or this is oss and there is no billing to upgrade
//            through. render nothing; an upgrade prompt here is an offer we
//            cannot honour.
export type GateState = "granted" | "locked" | "absent";

type Entitlements = {
  /** null until the profile lands, and for a signed-out visitor */
  edition: Edition | null;
  isCloud: boolean;
  gate: (feature: Feature) => GateState;
  hasInsights: boolean;
  hasEvents: boolean;
  hasRBAC: boolean;
  hasBilling: boolean;
};

export function useEntitlements(): Entitlements {
  const { user } = useAuth();
  const features = user?.features;
  const locked = user?.locked_features;
  const edition = user?.edition ?? null;

  const gate = useCallback(
    (feature: Feature): GateState => {
      if (features?.includes(feature)) return "granted";
      if (locked?.includes(feature)) return "locked";
      return "absent";
    },
    [features, locked],
  );

  return {
    edition,
    isCloud: edition === "cloud",
    gate,
    hasInsights: gate("insights") === "granted",
    // the audit/event router: workspace event log + per-experiment activity
    hasEvents: gate("event_log") === "granted",
    hasRBAC: gate("rbac") === "granted",
    // never feature-gated: a free tenant has to be able to reach billing in
    // order to upgrade
    hasBilling: edition === "cloud",
  };
}

// for a page that exists only to show a feature: once the profile has said the
// deployment does not offer it, the route is a 404, not an empty shell. locked
// still renders, so the page can offer the upgrade.
export function useFeatureRoute(feature: Feature): void {
  const { edition, gate } = useEntitlements();
  if (edition !== null && gate(feature) === "absent") notFound();
}
