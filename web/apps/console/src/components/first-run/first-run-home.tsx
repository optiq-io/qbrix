"use client";

import { EmptyState } from "@qbrix/ui/components/empty-state";
import { ExperimentsEmptyIcon } from "@qbrix/ui/components/empty-icons";
import { useWorkspaceName } from "@/components/shell/workspace-row";
import { useAuth } from "@/lib/auth/context";
import { docsUrl, routes } from "@/config/routes";
import { QuickStart } from "./quick-start";
import { ApiKeyPanel } from "./api-key-panel";

// board `APP · First run · empty console`. Home renders this instead of the
// pulse + tables while the workspace has no experiments: four zero-value stat
// cards and three empty tables tell a new tenant nothing about what to do.

export function FirstRunHome({ hasPools }: { hasPools: boolean }) {
  const { user } = useAuth();
  const workspace = useWorkspaceName();

  const firstName = user?.name?.split(" ")[0];
  const plan = user?.plan_tier
    ? user.plan_tier.charAt(0).toUpperCase() + user.plan_tier.slice(1)
    : null;

  // steps 1 and 2 are one action — see quick-start.tsx. step 4 reads the
  // profile's selection counter rather than clickhouse, which is gated above
  // the tier every tenant on this screen is on.
  const hasSelections = (user?.usage?.selections_this_period ?? 0) > 0;
  const done = [hasPools, hasPools, false, hasSelections];

  return (
    <div className="flex flex-1 flex-col gap-5 px-7 py-7">
      <div className="flex flex-col gap-[7px]">
        <h1 className="text-[25px] font-semibold tracking-[-0.85px] text-text-primary">
          {firstName ? `Welcome to qbrix, ${firstName}` : "Welcome to qbrix"}
        </h1>
        <p className="text-[14px] text-text-dim">
          {[workspace, plan && `${plan} plan`, "nothing running yet"]
            .filter(Boolean)
            .join(" · ")}
          . Four steps and your first decision is live.
        </p>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        <QuickStart done={done} />
        <ApiKeyPanel />
      </div>

      {/* the board wraps this in a `$bg-raised` panel with an EXPERIMENTS / 0
          head row. that chrome is dropped from every empty state
          on the grounds that the page's own surface is the panel — so this one
          sits on the ground too rather than reintroducing it here. */}
      <div className="flex items-center justify-center px-6 py-10">
        <EmptyState
          icon={<ExperimentsEmptyIcon />}
          title="No experiments yet"
          description="Once an experiment is running this is where you watch it converge — allocation, reward rate and throughput per variant, updating live."
          primaryAction={{
            label: "New experiment",
            href: routes.newExperiment(),
            shape: "create",
          }}
          secondaryAction={{
            label: "Read the quickstart",
            href: docsUrl("getting-started"),
            external: true,
          }}
        />
      </div>
    </div>
  );
}
