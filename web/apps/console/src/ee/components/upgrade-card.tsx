"use client";

import { useRouter } from "next/navigation";
import { Lock } from "lucide-react";
import { StateActions } from "@qbrix/ui/components/state-actions";
import { routes } from "@/config/routes";

// board `APP · Empty, loading & error states` / `INSIGHTS · GATED` (node
// VD84Z). the board wraps it in a $bg-raised r12 panel with a head row; the
// panel is dropped — states render on the page
// ground, same as Pools and the experiment tabs.
//
// the board's head carried the required tier as a lime `GROWTH` chip on the
// right. with the head gone that job falls to the CTA, which names the tier
// outright ("Upgrade to Growth") — better than a chip either way.
//
// this renders the **locked** state only. absent is `null`, and FeatureGate
// decides which — see feature-gate.tsx.
export function UpgradeCard({
  title,
  description,
  ctaLabel,
}: {
  title: string;
  description: string;
  /** "Upgrade to Growth" — the tier comes from FEATURE_MIN_TIER, never from
      the caller guessing */
  ctaLabel: string;
}) {
  const router = useRouter();

  return (
    <div className="flex flex-col items-center justify-center px-[26px] py-24">
      <div className="flex size-[46px] items-center justify-center rounded-xl border border-accent-dim bg-accent-soft">
        <Lock size={19} className="text-accent" />
      </div>

      <h3 className="pt-5 text-center text-[15.5px] font-semibold tracking-[-0.3px] text-text-primary">
        {title}
      </h3>

      <p className="max-w-[420px] pt-[9px] text-center text-[12.5px] leading-[1.55] text-text-dim">
        {description}
      </p>

      <StateActions
        className="pt-5"
        primary={{
          label: ctaLabel,
          onClick: () => router.push(routes.settingsBilling),
        }}
        // the board draws an `arrow-up-right` here, its convention for leaving
        // the app, to the www pricing page. this stays in-app on the plan
        // selector, so no arrow.
        secondary={{
          label: "Compare plans",
          onClick: () => router.push(routes.onboardingBilling),
        }}
      />
    </div>
  );
}
