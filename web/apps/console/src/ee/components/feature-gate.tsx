"use client";

import { useEntitlements } from "@/lib/entitlements";
import type { Feature } from "@/lib/entitlements";
import { FEATURE_MIN_TIER } from "@/ee/lib/billing/plans";
import { UpgradeCard } from "./upgrade-card";

// what a surface renders when its feature is unavailable. one line at the call
// site — `if (!hasInsights) return <FeatureGate surface="experiment.arms" />` —
// so no page has to remember that "unavailable" has two meanings:
//
//   locked → the UpgradeCard, naming the tier that unlocks it
//   absent → null. the deployment does not offer the feature at all, so an
//            upgrade prompt there is an offer we cannot honour.
//
// the copy for every gated surface lives in the one map below, which is the
// only way "all five read as one voice" stays true after the third person
// edits one of them.

type Surface =
  | "experiment.overview"
  | "experiment.arms"
  | "experiment.insights"
  | "experiment.activity"
  | "event-log";

const TIER_LABEL: Record<string, string> = {
  free: "Free",
  starter: "Starter",
  growth: "Growth",
  scale: "Scale",
  enterprise: "Enterprise",
};

// descriptions name only what the surface actually shows.
//
// the board's Insights copy read "Per-variant lift, posterior evolution and
// segment breakdowns" — segmentation has no source at all (ClickHouse
// holds context_metadata as an opaque blob and no endpoint groups on it), and
// posterior evolution is the Arms belief viz, not Insights. selling either one
// here would be a promise the product does not keep.
const GATED_SURFACES: Record<
  Surface,
  { feature: Feature; title: string; description: string }
> = {
  "experiment.overview": {
    feature: "insights",
    title: "Live metrics are on Growth",
    description:
      "Selections, reward rate and traffic share for this experiment, updating as feedback arrives. Your data is already being collected — this unlocks the view of it.",
  },
  "experiment.arms": {
    feature: "insights",
    title: "Per-variant belief is on Growth",
    description:
      "Reward rate, observed range and traffic share for every variant, with the belief curve each one has built up. Your data is already being collected — this unlocks the view of it.",
  },
  "experiment.insights": {
    feature: "insights",
    title: "Insights is on Growth",
    description:
      "Cumulative reward, lift against control, reward rate per variant and traffic share over time. Your data is already being collected — this unlocks the view of it.",
  },
  "experiment.activity": {
    feature: "event_log",
    title: "Activity is on Scale",
    description:
      "Every selection, reward and configuration change on this experiment, in the order it happened.",
  },
  "event-log": {
    feature: "event_log",
    title: "The event log is on Scale",
    description:
      "Every selection, reward and configuration change across the workspace, as it happens, with the full payload behind each one.",
  },
};

export function FeatureGate({ surface }: { surface: Surface }) {
  const { gate } = useEntitlements();
  const { feature, title, description } = GATED_SURFACES[surface];

  if (gate(feature) !== "locked") return null;

  return (
    <UpgradeCard
      title={title}
      description={description}
      ctaLabel={`Upgrade to ${TIER_LABEL[FEATURE_MIN_TIER[feature]]}`}
    />
  );
}
