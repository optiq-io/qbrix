import { Suspense } from "react";
import { PlanSelector } from "@/ee/components/billing/plan-selector";

export default function OnboardingBillingPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-bg" />}>
      <PlanSelector />
    </Suspense>
  );
}
