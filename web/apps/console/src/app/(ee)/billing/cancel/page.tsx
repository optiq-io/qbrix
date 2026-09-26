"use client";

import Link from "next/link";
import { Undo2 } from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { useAuth } from "@/lib/auth/context";
import { planLabel } from "@/ee/lib/billing/plans";
import { TransactionalCard } from "@/components/auth/transactional-card";
import { OutcomeShell } from "@/ee/components/billing/outcome-shell";
import { routes } from "@/config/routes";

// board `APP · Billing outcome` / /billing/cancel. the board names the free
// plan directly, but this is also where a paid tenant lands after abandoning an
// upgrade, so the tier comes from the profile — on free it reads as drawn.
export default function BillingCancelPage() {
  const { user } = useAuth();
  const label = user?.plan_tier ? planLabel(user.plan_tier) : null;

  return (
    <OutcomeShell tone="neutral">
      <TransactionalCard
        icon={Undo2}
        tone="neutral"
        title="Checkout cancelled"
        body={
          label
            ? `No charge was made and nothing changed. You are still on the ${label} plan and can upgrade whenever you are ready.`
            : "No charge was made and nothing changed. You can upgrade whenever you are ready."
        }
      >
        <Link href={routes.onboardingBilling} className="w-full">
          <Button className="h-12 w-full text-[15.5px]">Back to plans</Button>
        </Link>
        <Link href={routes.home} className="w-full">
          <Button variant="secondary" className="h-12 w-full text-[15.5px]">
            {label ? `Continue on ${label}` : "Back to the console"}
          </Button>
        </Link>
      </TransactionalCard>
    </OutcomeShell>
  );
}
