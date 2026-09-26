import type { User } from "@/lib/api/types";

// taken from the wire field rather than restated, so a new tier cannot be known
// to one side and not the other
export type PlanTier = NonNullable<User["plan_tier"]>;

// self-serve, usage-metered tiers — the only ones the usage meter renders for.
export const METERED_TIERS: readonly PlanTier[] = ["starter", "growth", "scale"];

export interface BillingSubscription {
  id: string;
  plan_tier: PlanTier;
  status: "active" | "canceled" | "past_due" | "trialing" | "inactive";
  current_period_start: number;
  current_period_end: number;
  cancel_at_period_end: boolean;
  canceled_at?: number;
}

// usage for the current billing period, from GET /api/v1/ee/billing/usage.
// 404s for free/enterprise/non-metered tenants — see useUsage().
export interface UsageView {
  used: number;
  included: number;
  overage: number;
  overage_cost: number; // minor units (cents), Stripe-rated
  currency: string;
  period_start: string;
  period_end: string;
}

// what a surface renders, resolved per tier by useSelectionUsage().
export interface SelectionUsage {
  used: number;
  /** null on enterprise — the included volume is contractual, so no bar */
  included: number | null;
  /** paid tiers only: the profile counter carries no billing figures */
  overage: number | null;
  overageCost: number | null;
  currency: string | null;
  periodStart: Date | null;
  periodEnd: Date | null;
  /** free: past `included`, further selections are rejected rather than billed */
  capped: boolean;
}

export interface BillingInvoice {
  id: string;
  amount_due: number;
  amount_paid: number;
  currency: string;
  status: "draft" | "open" | "paid" | "void" | "uncollectible";
  invoice_pdf?: string;
  created_at: number;
}

export interface CheckoutSession {
  session_id: string;
  url: string;
}

export interface PortalSession {
  url: string;
}

export interface ChangePreview {
  target_tier: PlanTier;
  currency: string;
  // minor units (e.g. cents); positive = charge, negative = credit
  proration_amount: number;
  next_invoice_total: number;
}
