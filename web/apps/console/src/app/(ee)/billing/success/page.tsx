"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Check, Loader } from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { MonoLabel } from "@qbrix/ui/components/mono-label";
import { cn } from "@qbrix/ui/lib/utils";
import { useAuth } from "@/lib/auth/context";
import { auth } from "@/lib/api/auth";
import { useSubscription } from "@/ee/lib/billing/hooks";
import { PLAN_CATALOGUE, planLabel, toPlanTier } from "@/ee/lib/billing/plans";
import { TransactionalCard } from "@/components/auth/transactional-card";
import { OutcomeShell } from "@/ee/components/billing/outcome-shell";
import { routes } from "@/config/routes";

// board `APP · Billing outcome`, the two /billing/success states.
//
// stripe redirects here the moment checkout completes, which can be before the
// webhook that provisions the tier has been delivered. the pending card is
// therefore what renders first — it is the honest state on arrival, and the
// customer can leave for the console from it rather than watch a spinner.
const POLL_DEADLINE_MS = 20_000;
const POLL_START_MS = 500;
const POLL_MAX_MS = 3_000;

function UnlockedList({ items }: { items: string[] }) {
  return (
    <ul className="w-full overflow-hidden rounded-[10px] border border-border-subtle bg-bg-raised">
      {items.map((item) => (
        <li
          key={item}
          className="flex items-center gap-[9px] px-3.5 py-[11px] text-left text-[13px] text-text-secondary"
        >
          <Check size={13} className="shrink-0 text-accent" />
          {item}
        </li>
      ))}
    </ul>
  );
}

function BillingSuccessContent() {
  const searchParams = useSearchParams();
  const expectedTier = toPlanTier(searchParams.get("plan"));
  const { user, updateUser } = useAuth();
  const { refetch } = useSubscription();

  const [confirmed, setConfirmed] = useState(false);
  const [polling, setPolling] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function waitForEntitlements() {
      const deadline = Date.now() + POLL_DEADLINE_MS;
      let delay = POLL_START_MS;

      while (!cancelled) {
        try {
          const profile = await auth.profile();
          if (cancelled) return;
          updateUser(profile);
          if (!expectedTier || profile.plan_tier === expectedTier) {
            setConfirmed(true);
            break;
          }
        } catch {
          // a failed poll is indistinguishable from a slow one — keep waiting
        }

        if (Date.now() >= deadline) break;
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay = Math.min(delay * 1.5, POLL_MAX_MS);
      }

      if (cancelled) return;
      await refetch();
      setPolling(false);
    }

    setPolling(true);
    waitForEntitlements();

    return () => {
      cancelled = true;
    };
  }, [expectedTier, refetch, updateUser, attempt]);

  if (confirmed) {
    // name the plan that was bought, not the one still on the profile — on a
    // slow webhook the latter is the *previous* tier, which would congratulate
    // the customer on the plan they just upgraded away from
    const tier = expectedTier ?? user?.plan_tier ?? null;
    const unlocked = tier ? PLAN_CATALOGUE[tier].unlocked : undefined;

    return (
      <OutcomeShell tone="accent">
        <TransactionalCard
          icon={Check}
          tone="accent"
          title={tier ? `Welcome to ${planLabel(tier)}` : "You're subscribed"}
          body={
            unlocked
              ? "Your subscription is active. Everything below is available right now."
              : "Your subscription is active."
          }
          meta={unlocked ? <UnlockedList items={unlocked} /> : undefined}
        >
          <Link href={routes.home} className="w-full">
            <Button className="h-12 w-full text-[15.5px]">
              Go to the console
            </Button>
          </Link>
        </TransactionalCard>
      </OutcomeShell>
    );
  }

  return (
    <OutcomeShell tone="info">
      <TransactionalCard
        icon={Loader}
        tone="info"
        title="Payment received"
        body="Your new features are still being activated and will appear shortly. You can keep working — nothing is lost."
        meta={
          <div className="flex items-center gap-[7px] rounded-md border border-border-subtle bg-bg-raised px-2.5 py-1">
            <span
              className={cn(
                "size-[5px] rounded-full bg-info",
                polling && "animate-pulse",
              )}
            />
            <MonoLabel tone="dim">Waiting on webhook</MonoLabel>
          </div>
        }
      >
        <Link href={routes.home} className="w-full">
          <Button className="h-12 w-full text-[15.5px]">
            Go to the console
          </Button>
        </Link>
        <Button
          variant="secondary"
          disabled={polling}
          onClick={() => setAttempt((n) => n + 1)}
          className="h-12 w-full text-[15.5px]"
        >
          Refresh
        </Button>
      </TransactionalCard>
    </OutcomeShell>
  );
}

export default function BillingSuccessPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-bg" />}>
      <BillingSuccessContent />
    </Suspense>
  );
}
