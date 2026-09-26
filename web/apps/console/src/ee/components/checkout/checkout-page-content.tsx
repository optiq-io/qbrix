"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Check, Loader2, Lock, ShieldCheck } from "lucide-react";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { useCreateCheckoutSession } from "@/ee/lib/billing/hooks";
import { useAuth } from "@/lib/auth/context";
import { useRuntimeConfig } from "@/ee/lib/config";
import {
  CHECKOUT_TIERS,
  OVERAGE_RATE,
  PLAN_CATALOGUE,
  planPrice,
  planPriceExact,
  planVolume,
  planVolumeExact,
  toPlanTier,
} from "@/ee/lib/billing/plans";
import type { PlanTier } from "@/ee/lib/billing/types";
import { routes } from "@/config/routes";

// board `APP · Checkout`. the board draws the card fields inline; the shipped
// flow hands off to stripe-hosted checkout and this ticket keeps those
// mechanics, so the left column explains the handoff and carries the cta while
// the order summary is built as drawn.
//
// the board's `VAT (reverse charge) €0.00` line is not rendered:
// create_checkout_session passes neither automatic_tax nor tax_id_collection,
// so no tax is computed and no vat id is collected. with nothing added, the
// total is simply the licence price.

const TRUST = [
  "Cancel or downgrade at any time",
  "Invoices and receipts in Settings → Billing",
  "Usage tracked in real time, never estimated",
];

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-6">
      {children}
    </div>
  );
}

export function CheckoutPageContent() {
  const searchParams = useSearchParams();
  const { user, loading } = useAuth();
  const { data: config, isLoading: configLoading } = useRuntimeConfig();
  const createCheckout = useCreateCheckoutSession();

  const requested = toPlanTier(searchParams.get("plan"));
  const tier: PlanTier =
    requested && CHECKOUT_TIERS.includes(requested) ? requested : "growth";
  const plan = PLAN_CATALOGUE[tier];

  if (loading) {
    return (
      <Shell>
        <Skeleton className="h-[420px] w-full max-w-[440px]" />
      </Shell>
    );
  }

  if (!user) return null;

  if (user.role !== "admin") {
    return (
      <Shell>
        <div className="flex w-full max-w-[420px] flex-col items-center gap-6 text-center">
          <div className="flex size-11 items-center justify-center rounded-[10px] bg-bg-panel text-text-dim">
            <ShieldCheck size={19} />
          </div>
          <div className="flex flex-col gap-2.5">
            <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em] text-text-primary">
              Only admins can change the plan
            </h1>
            <p className="text-[14px] leading-[1.6] text-text-dim">
              Billing is managed at the workspace level. Ask a workspace admin
              to upgrade to {plan.name}.
            </p>
          </div>
          <Link
            href={routes.home}
            className="flex h-12 w-full items-center justify-center rounded-full border border-border-strong bg-bg-panel text-[15.5px] font-medium text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
          >
            Back to the console
          </Link>
        </div>
      </Shell>
    );
  }

  const priceId =
    tier === "starter"
      ? config?.stripePriceIdStarter
      : tier === "growth"
        ? config?.stripePriceIdGrowth
        : config?.stripePriceIdScale;

  function handleContinue() {
    if (!priceId) return;
    // the success page waits for the profile to report this tier before it
    // claims the features are unlocked
    const successUrl = `${window.location.origin}/billing/success?session_id={CHECKOUT_SESSION_ID}&plan=${tier}`;
    const cancelUrl = `${window.location.origin}/checkout?plan=${tier}`;
    createCheckout.mutate({ priceId, successUrl, cancelUrl });
  }

  const disabled = configLoading || !priceId || createCheckout.isPending;

  return (
    <div className="flex min-h-screen flex-col bg-bg lg:flex-row">
      <div className="flex flex-1 flex-col px-6 py-10 md:px-12 lg:px-20">
        <Link
          href={routes.onboardingBilling}
          className="flex items-center gap-2 text-[13.5px] text-text-dim transition-colors hover:text-text-primary"
        >
          <ArrowLeft size={15} className="text-text-faint" />
          Back to plans
        </Link>

        <div className="pt-16">
          <div className="w-full max-w-[440px]">
            <h1 className="text-[30px] font-semibold leading-[1.15] tracking-[-1px] text-text-primary">
              Payment details
            </h1>
            <p className="pt-2 text-[14.5px] leading-[1.55] text-text-dim">
              Secured by Stripe. You can cancel or change plan at any time.
            </p>

            <div className="mt-7 flex flex-col gap-3 rounded-[12px] border border-border-subtle bg-bg-panel p-5">
              {[
                "Card details are entered on Stripe, never on qbrix",
                "Your workspace upgrades the moment payment clears",
              ].map((line) => (
                <div key={line} className="flex gap-2.5">
                  <Check size={14} className="mt-0.5 shrink-0 text-accent" />
                  <span className="text-[13.5px] leading-[1.5] text-text-secondary">
                    {line}
                  </span>
                </div>
              ))}
            </div>

            <button
              type="button"
              onClick={handleContinue}
              disabled={disabled}
              className="mt-7 flex h-12 w-full items-center justify-center gap-2.5 rounded-[10px] bg-accent text-[15px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
            >
              {createCheckout.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Lock size={14} />
              )}
              Continue to payment · {planPrice(tier)} / month
            </button>

            <p className="pt-3.5 text-[12.5px] leading-[1.55] text-text-faint">
              You will be charged {planPrice(tier)} today and on the same day
              each month. Overage for the previous month is added to the next
              invoice.
            </p>
          </div>
        </div>
      </div>

      <div className="flex flex-col border-border-subtle bg-bg-panel px-6 py-10 md:px-12 lg:w-[520px] lg:border-l lg:px-12 lg:pt-[104px]">
        <span className="font-mono text-[11px] uppercase tracking-[0.118em] text-text-faint">
          Order summary
        </span>

        <div className="mt-6 rounded-[12px] border border-accent-dim bg-bg-raised p-5">
          <div className="flex items-start justify-between gap-4">
            <span className="text-[18px] font-semibold text-text-primary">
              {plan.name}
            </span>
            <span className="text-[22px] font-semibold text-text-primary">
              {planPrice(tier)}
            </span>
          </div>
          <div className="flex items-baseline justify-between gap-4 pt-1.5">
            <span className="text-[13px] text-text-dim">
              {planVolume(tier)}
            </span>
            <span className="text-[13px] text-text-faint">per month</span>
          </div>
        </div>

        <div className="mt-4 overflow-hidden rounded-[12px] border border-border-subtle">
          <Row label={`${plan.name} licence`} value={planPriceExact(tier)} />
          <Row
            label="Included selections"
            value={planVolumeExact(tier)}
            divided
          />
          <Row label="Overage rate" value={OVERAGE_RATE} divided />
          <div className="flex items-center justify-between gap-4 border-t border-border-subtle bg-bg-raised p-4">
            <span className="text-[15px] font-semibold text-text-primary">
              Due today
            </span>
            <span className="text-[20px] font-semibold text-accent">
              {planPriceExact(tier)}
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-[11px] pt-[26px]">
          {TRUST.map((line) => (
            <div key={line} className="flex items-center gap-2.5">
              <Check size={15} className="shrink-0 text-text-faint" />
              <span className="text-[13.5px] text-text-dim">{line}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  divided,
}: {
  label: string;
  value: string;
  divided?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-4 px-4 py-[13px] ${
        divided ? "border-t border-border-subtle" : ""
      }`}
    >
      <span className="text-[14px] text-text-secondary">{label}</span>
      <span className="text-[13px] tabular-nums text-text-secondary">
        {value}
      </span>
    </div>
  );
}
