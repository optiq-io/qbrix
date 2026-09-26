import type { Feature } from "@/lib/entitlements";
import type { PlanTier } from "./types";

// mirrors FEATURE_MIN_TIER in svc/proxy/src/proxysvc/ee/plans.py, and is only
// ever used to name a tier in upsell copy. no gate consults it — a gate is the
// backend's answer in `features` / `locked_features`, never a matrix re-derived
// on the client.
export const FEATURE_MIN_TIER: Record<Feature, PlanTier> = {
  insights: "growth",
  event_log: "scale",
  rbac: "scale",
  sso: "scale",
};

const TIERS: readonly string[] = [
  "free",
  "starter",
  "growth",
  "scale",
  "enterprise",
];

export function planLabel(tier: PlanTier): string {
  return tier.charAt(0).toUpperCase() + tier.slice(1);
}

/** narrows a `?plan=` query param, which anyone can type anything into */
export function toPlanTier(value: string | null): PlanTier | null {
  return value && TIERS.includes(value) ? (value as PlanTier) : null;
}

export const OVERAGE_RATE = "€10 / 100K";

export const OVERAGE_NOTE =
  "Overage is billed at €10 per additional 100,000 selections on every paid plan.";

export interface PlanEntry {
  name: string;
  /** minor units; null on enterprise, where the price is contractual */
  amountMinor: number | null;
  /** null on enterprise — a contractual volume has no number to render */
  includedSelections: number | null;
  blurb: string;
  features: string[];
  cta: string;
  /** what the upgrade bought, for the confirmed billing outcome */
  unlocked?: string[];
}

// boards `APP · Onboarding / Plan selector` and `APP · Checkout`.
//
// the volumes mirror PLAN_LIMITS in svc/proxy/src/proxysvc/ee/plans.py and
// the prices live only in stripe. neither can be read from the api:
// PLAN_LIMITS carries no prices, and the endpoint that exposes it returns the
// caller's own row rather than all five tiers.
// this module is the single seam that a GET /v1/plans would replace.
//
// every string below has to resolve to PLAN_LIMITS, FEATURE_MIN_TIER or a
// stripe price — these render in the plan selector, the checkout page and the
// post-payment receipt, so a wrong one is read at the moment money changes
// hands. four that did not were removed: two enterprise capabilities our
// own Terms and entitlement model deny outright, an identity-protocol claim
// with nothing implementing it, and a Starter differentiator that is not
// tier-gated at all. the exact strings are on the ticket, deliberately not
// repeated here so a claims grep over this tree stays clean.
//
// the marketing site's `apps/www/src/lib/plans.ts` (in its own repository) is
// the same catalogue, and the two should stay diffable by eye. they differ in
// one place on purpose: SSO carries a "(coming soon)" qualifier here, because
// checkout is a stronger context than a pricing table.
export const PLAN_CATALOGUE: Record<PlanTier, PlanEntry> = {
  free: {
    name: "Free",
    amountMinor: 0,
    includedSelections: 100_000,
    blurb: "Get started with essential features",
    features: [
      "Hard-capped at quota",
      "3 active experiments",
      "3 seats · 2 API keys",
      "Every policy, on every plan",
      "Community support",
    ],
    cta: "Start free",
  },
  starter: {
    name: "Starter",
    amountMinor: 99_00,
    includedSelections: 1_000_000,
    blurb: "For early-stage teams shipping to production",
    features: [
      "Unlimited experiments",
      "Unlimited seats and keys",
      "No hard volume cap",
      "Email support",
      "€10 per extra 100K",
    ],
    cta: "Upgrade to Starter",
    unlocked: [
      "1,000,000 selections / month",
      "Unlimited experiments",
      "No hard volume cap",
      "Email support",
    ],
  },
  growth: {
    name: "Growth",
    amountMinor: 699_00,
    includedSelections: 10_000_000,
    blurb: "For scaling teams that live in the numbers",
    features: [
      "Everything in Starter",
      "Insights & dashboards",
      "Priority support",
      "€10 per extra 100K",
    ],
    cta: "Upgrade to Growth",
    unlocked: [
      "10,000,000 selections / month",
      "Insights & dashboards",
      "Priority support",
    ],
  },
  scale: {
    name: "Scale",
    amountMinor: 2_900_00,
    includedSelections: 50_000_000,
    blurb: "For teams with governance requirements",
    features: [
      "Everything in Growth",
      "Role assignment",
      "Event log & audit trail",
      "SSO (coming soon)",
      "Dedicated support & guided onboarding",
    ],
    cta: "Upgrade to Scale",
    // no SSO here, deliberately: `unlocked` answers "what did this payment
    // just buy you", and `sso` is a FEATURE_MIN_TIER entry with no
    // implementation behind it. it belongs in `features` with its qualifier
    // and nowhere else until it ships.
    unlocked: [
      "50,000,000 selections / month",
      "Role assignment",
      "Event log & audit trail",
      "Dedicated support & guided onboarding",
    ],
  },
  enterprise: {
    name: "Enterprise",
    amountMinor: null,
    includedSelections: null,
    blurb: "For organizations that need full control",
    features: [
      "Custom selection volume",
      "Custom agreements",
      "Security review",
      "Dedicated support",
    ],
    cta: "Talk to sales",
  },
};

/** the order the selector renders, and the order tiers rank in */
export const PLAN_ORDER: PlanTier[] = [
  "free",
  "starter",
  "growth",
  "scale",
  "enterprise",
];

/** tiers with a stripe price behind them — the only ones that can check out */
export const CHECKOUT_TIERS: PlanTier[] = ["starter", "growth", "scale"];

function eur(minor: number, decimals: number): string {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(minor / 100);
}

/** headline form: `€699`, `Custom` */
export function planPrice(tier: PlanTier): string {
  const amount = PLAN_CATALOGUE[tier].amountMinor;
  return amount === null ? "Custom" : eur(amount, 0);
}

/** invoice form: `€699.00` */
export function planPriceExact(tier: PlanTier): string {
  const amount = PLAN_CATALOGUE[tier].amountMinor;
  return amount === null ? "Custom" : eur(amount, 2);
}

/** card form: `10M selections / mo` */
export function planVolume(tier: PlanTier): string {
  const n = PLAN_CATALOGUE[tier].includedSelections;
  if (n === null) return "Custom selections / mo";
  // en-GB compact gives a lowercase suffix (`10m`); the board sets `10M`
  const compact = new Intl.NumberFormat("en-GB", {
    notation: "compact",
    maximumFractionDigits: 0,
  })
    .format(n)
    .toUpperCase();
  return `${compact} selections / mo`;
}

/** summary form: `10,000,000` */
export function planVolumeExact(tier: PlanTier): string {
  const n = PLAN_CATALOGUE[tier].includedSelections;
  return n === null ? "Custom" : n.toLocaleString("en-GB");
}
