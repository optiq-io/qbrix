"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Check, Loader2 } from "lucide-react";
import { QbrixBrick } from "@qbrix/ui/components/logo";
import { cn } from "@qbrix/ui/lib/utils";
import { useCreateCheckoutSession } from "@/ee/lib/billing/hooks";
import { useAuth } from "@/lib/auth/context";
import { useRuntimeConfig } from "@/ee/lib/config";
import {
  CHECKOUT_TIERS,
  OVERAGE_NOTE,
  PLAN_CATALOGUE,
  PLAN_ORDER,
  planPrice,
  planVolume,
} from "@/ee/lib/billing/plans";
import type { PlanTier } from "@/ee/lib/billing/types";
import { routes } from "@/config/routes";

// board `APP · Onboarding / Plan selector`.
//
// the stepper and "Skip for now" only make sense inside the signup funnel, but
// this page is also the console's only "compare the tiers" surface — the gated
// UpgradeCard sends existing users here. both are therefore gated on
// `?from=onboarding`, which the verify-email CTA passes.

const STEPS = ["Account", "Verify", "Plan", "Ship"] as const;

function Steps() {
  return (
    <div className="flex items-center gap-2.5">
      {STEPS.map((step, i) => {
        const done = i < 2;
        const current = step === "Plan";
        return (
          <div key={step} className="flex items-center gap-2.5">
            {i > 0 && <span className="h-px w-[26px] bg-border" />}
            <div className="flex items-center gap-[7px]">
              <span
                className={cn(
                  "flex size-4 items-center justify-center rounded-full border",
                  done && "border-border bg-accent",
                  current && "border-accent bg-accent-soft",
                  !done && !current && "border-border bg-bg-raised",
                )}
              >
                {done && <Check size={10} className="text-bg" />}
              </span>
              <span
                className={cn(
                  "font-mono text-[11px] uppercase tracking-[0.073em]",
                  current ? "text-accent" : done ? "text-text-dim" : "text-text-faint",
                )}
              >
                {step}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function PlanSelector() {
  const searchParams = useSearchParams();
  const onboarding = searchParams.get("from") === "onboarding";

  const { user } = useAuth();
  const { data: config, isLoading: configLoading } = useRuntimeConfig();
  const createCheckout = useCreateCheckoutSession();

  // POST /checkout/session is require_admin_user
  const isAdmin = user?.role === "admin";
  const currentTier = user?.plan_tier;

  const priceIdFor = (tier: PlanTier) =>
    tier === "starter"
      ? config?.stripePriceIdStarter
      : tier === "growth"
        ? config?.stripePriceIdGrowth
        : tier === "scale"
          ? config?.stripePriceIdScale
          : undefined;

  function handleUpgrade(tier: PlanTier) {
    if (!isAdmin) return;
    const priceId = priceIdFor(tier);
    if (!priceId) return;
    const successUrl = `${window.location.origin}/billing/success?session_id={CHECKOUT_SESSION_ID}&plan=${tier}`;
    const cancelUrl = `${window.location.origin}/billing/cancel`;
    createCheckout.mutate({ priceId, successUrl, cancelUrl });
  }

  return (
    <div className="flex min-h-screen flex-col items-center bg-bg px-6 pb-14 pt-14 md:px-12">
      <Link
        href="https://qbrix.io"
        className="flex items-center gap-2.5 transition-opacity hover:opacity-70"
      >
        <QbrixBrick size={22} />
        <span className="font-heading text-[15px] font-semibold text-text-primary">
          qbrix
        </span>
      </Link>

      {onboarding && (
        <div className="pt-11">
          <Steps />
        </div>
      )}

      <h1 className="pt-[30px] text-center text-[40px] font-semibold leading-[1.15] tracking-[-1.5px] text-text-primary">
        Choose your plan
      </h1>
      <p className="max-w-[700px] pt-3 text-center text-[16.5px] leading-[1.6] text-text-dim">
        Every plan includes a monthly selection volume. Start free — you can
        change or cancel at any time, and nothing is charged until you cross the
        line you picked.
      </p>

      {!isAdmin && (
        <p className="pt-5 text-center text-[13.5px] text-text-faint">
          Only workspace admins can change the plan. Ask an admin to upgrade.
        </p>
      )}

      <div className="grid w-full max-w-[1344px] grid-cols-1 gap-3.5 pt-11 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {PLAN_ORDER.map((tier) => {
          const plan = PLAN_CATALOGUE[tier];
          const popular = tier === "growth";
          const isCurrent = tier === currentTier;
          const checkoutable = CHECKOUT_TIERS.includes(tier);
          const pending =
            createCheckout.isPending && createCheckout.variables?.priceId === priceIdFor(tier);

          return (
            <div
              key={tier}
              className={cn(
                "flex flex-col rounded-[14px] border p-5",
                popular
                  ? "border-accent bg-bg-raised"
                  : "border-border-subtle bg-bg",
              )}
            >
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-semibold text-text-primary">
                  {plan.name}
                </span>
                {popular && (
                  <span className="rounded px-[7px] py-0.5 font-mono text-[9px] uppercase tracking-[0.067em] text-accent bg-accent-soft">
                    Popular
                  </span>
                )}
              </div>

              <div className="flex items-end gap-1.5 pt-3.5">
                <span className="text-[32px] leading-none text-text-primary">
                  {planPrice(tier)}
                </span>
                {plan.amountMinor !== null && (
                  <span className="pb-1.5 font-mono text-[11px] text-text-faint">
                    / month
                  </span>
                )}
              </div>

              <p
                className={cn(
                  "pt-1.5 text-[11.5px]",
                  popular ? "text-accent" : "text-text-dim",
                )}
              >
                {planVolume(tier)}
              </p>

              <p className="pt-3 text-[12.5px] leading-[1.45] text-text-faint">
                {plan.blurb}
              </p>

              <div className="flex flex-col gap-[9px] pt-[18px]">
                {plan.features.map((feature) => (
                  <div key={feature} className="flex gap-2">
                    <Check size={13} className="mt-0.5 shrink-0 text-accent" />
                    <span className="text-[12.5px] leading-[1.45] text-text-secondary">
                      {feature}
                    </span>
                  </div>
                ))}
              </div>

              <div className="flex-1 pt-5" />

              {tier === "enterprise" ? (
                <a
                  href="mailto:info@optiqio.com"
                  className="flex h-10 items-center justify-center rounded-[9px] border border-border-strong text-[13px] font-semibold text-text-primary transition-colors hover:bg-bg-hover"
                >
                  {plan.cta}
                </a>
              ) : isCurrent || !checkoutable ? (
                <span className="flex h-10 items-center justify-center rounded-[9px] border border-border-subtle text-[13px] font-semibold text-text-faint">
                  {isCurrent ? "Current plan" : plan.cta}
                </span>
              ) : isAdmin ? (
                <button
                  type="button"
                  onClick={() => handleUpgrade(tier)}
                  disabled={configLoading || !priceIdFor(tier) || createCheckout.isPending}
                  className={cn(
                    "flex h-10 items-center justify-center gap-2 rounded-[9px] text-[13px] font-semibold transition-colors disabled:opacity-50",
                    popular
                      ? "bg-accent text-bg hover:bg-accent/90"
                      : "border border-border-strong text-text-primary hover:bg-bg-hover",
                  )}
                >
                  {pending && <Loader2 size={13} className="animate-spin" />}
                  {plan.cta}
                </button>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-center gap-6 pt-[30px]">
        <p className="text-[13.5px] text-text-faint">{OVERAGE_NOTE}</p>
        {onboarding && (
          <>
            <span className="size-[3px] rounded-full bg-text-faint" />
            <Link
              href={routes.home}
              className="text-[13.5px] font-semibold text-text-dim transition-colors hover:text-text-primary"
            >
              Skip for now
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
