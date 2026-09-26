"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { ColumnBar, DataRow, Cell } from "@qbrix/ui/components/data-table";
import type { Column } from "@qbrix/ui/components/data-table";
import { ConfirmDialog } from "@qbrix/ui/components/confirm-dialog";
import { ErrorState } from "@qbrix/ui/components/error-state";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import {
  useSubscription,
  useInvoices,
  useCancelSubscription,
  useReactivateSubscription,
  useCreatePortalSession,
  useChangeSubscription,
  useSubscriptionChangePreview,
} from "@/ee/lib/billing/hooks";
import { METERED_TIERS as SELF_SERVE_TIERS, type PlanTier } from "@/ee/lib/billing/types";
import { useAuth } from "@/lib/auth/context";
import { formatMoney } from "@/ee/lib/billing/format";
import { planLabel } from "@/ee/lib/billing/plans";
import { apiErrorCode } from "@/lib/api/handle-error";
import { UsageMeter } from "@/ee/components/billing/usage-meter";
import { routes } from "@/config/routes";
import { SettingsHead, formatDay } from "@/components/settings/chrome";

// sibling of `APP · Settings / API Keys`, which is the only other v3 settings
// tab and the template for all of this: heading band on a hairline, padded
// body, then an edge-to-edge list. no board was drawn for billing and none was
// commissioned — every element here already had a shipped pattern.

const COLUMNS: Column[] = [
  { label: "Date" },
  { label: "Amount", width: 120, align: "right" },
  { label: "Status", width: 110 },
  { label: "Invoice", width: 110, align: "right" },
];

// StateBadge is keyed to ExperimentState, a closed union of experiment states,
// so it cannot carry a subscription status. this keeps its alpha discipline —
// /10 ground, /20 hairline — without widening that enum.
function StatusPill({ tone, label }: { tone: "accent" | "danger"; label: string }) {
  return (
    <span
      className={
        tone === "accent"
          ? "inline-flex h-[22px] shrink-0 items-center rounded-full border border-accent/20 bg-accent/10 px-2.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-accent"
          : "inline-flex h-[22px] shrink-0 items-center rounded-full border border-danger/20 bg-danger/10 px-2.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-danger"
      }
    >
      {label}
    </span>
  );
}

export function BillingTab() {
  const { user } = useAuth();
  const { data: subscription, isLoading: subLoading } = useSubscription();
  const invoices = useInvoices();
  const cancelSubscription = useCancelSubscription();
  const reactivateSubscription = useReactivateSubscription();
  const portalSession = useCreatePortalSession();

  const [cancelOpen, setCancelOpen] = useState(false);
  const [pendingChange, setPendingChange] = useState<PlanTier | null>(null);

  const openPortal = () =>
    portalSession.mutate(
      typeof window !== "undefined" ? window.location.href : undefined,
    );

  // every mutating billing route is require_admin_user; the reads are not
  const isAdmin = user?.role === "admin";

  const isPaidPlan =
    !!subscription?.plan_tier &&
    subscription.plan_tier !== "free" &&
    subscription.status === "active";
  const isCanceled = !!subscription?.cancel_at_period_end;
  const planDisplayName = subscription?.plan_tier
    ? planLabel(subscription.plan_tier)
    : "Free";

  // free tier comes back as `current_period_end: 0`, and `0 && …` renders the
  // zero rather than nothing — the stray "0" this tab used to show
  const hasPeriodEnd = !!subscription?.current_period_end;

  const showUpgrade =
    !subscription ||
    subscription.plan_tier === "free" ||
    subscription.plan_tier === "starter" ||
    subscription.plan_tier === "growth";

  const currentIdx = subscription
    ? SELF_SERVE_TIERS.indexOf(subscription.plan_tier)
    : -1;
  const nextTier =
    currentIdx >= 0 && currentIdx < SELF_SERVE_TIERS.length - 1
      ? SELF_SERVE_TIERS[currentIdx + 1]
      : null;
  const prevTier = currentIdx > 0 ? SELF_SERVE_TIERS[currentIdx - 1] : null;

  const rows = invoices.data?.invoices ?? [];

  return (
    <div className="flex flex-1 flex-col">
      <SettingsHead
        title="Billing"
        description={
          <>
            Your plan, the selections it includes, and every invoice we have
            issued. Payment details live in the Stripe portal.
            {!isAdmin &&
              " Only workspace admins can change the plan or payment details."}
          </>
        }
        meta={
          <>
            <div className="flex items-center gap-2.5">
              <span className="text-[15px] font-medium text-text-primary">
                {subLoading ? "—" : planDisplayName}
              </span>
              {!subLoading && isCanceled && (
                <StatusPill tone="danger" label="Canceling" />
              )}
              {!subLoading && isPaidPlan && !isCanceled && (
                <StatusPill tone="accent" label="Active" />
              )}
            </div>
            {hasPeriodEnd && subscription && (
              <span className="text-[13px] text-text-faint">
                {isCanceled ? "Access until " : "Renews "}
                {formatDay(subscription.current_period_end)}
              </span>
            )}
          </>
        }
      />

      <div className="flex flex-col gap-6 border-b border-border-subtle px-7 py-6">
        <UsageMeter />

        {isCanceled && (
          <p className="text-[13px] leading-[1.5] text-text-dim">
            This subscription is set to cancel at the end of the billing period.
            Reactivate to keep it running.
          </p>
        )}

        {isAdmin && (
          <div className="flex flex-wrap items-center gap-2.5">
            {isPaidPlan && (
              <button
                type="button"
                onClick={openPortal}
                disabled={portalSession.isPending}
                className="flex h-9 shrink-0 items-center gap-2 rounded-full bg-accent px-4 text-[14.5px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
              >
                {portalSession.isPending && (
                  <Loader2 size={14} className="animate-spin" />
                )}
                Manage subscription
              </button>
            )}

            {isPaidPlan && !isCanceled && (
              <button
                type="button"
                onClick={() => setCancelOpen(true)}
                className="flex h-9 shrink-0 items-center rounded-full border border-border-strong bg-bg-panel px-4 text-[14.5px] font-medium text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
              >
                Cancel subscription
              </button>
            )}

            {isPaidPlan && isCanceled && (
              <button
                type="button"
                onClick={() => reactivateSubscription.mutate()}
                disabled={reactivateSubscription.isPending}
                className="flex h-9 shrink-0 items-center gap-2 rounded-full bg-accent px-4 text-[14.5px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
              >
                {reactivateSubscription.isPending && (
                  <Loader2 size={14} className="animate-spin" />
                )}
                Reactivate
              </button>
            )}

            {isPaidPlan && !isCanceled && prevTier && (
              <button
                type="button"
                onClick={() => setPendingChange(prevTier)}
                className="flex h-9 shrink-0 items-center rounded-full border border-border-strong bg-bg-panel px-4 text-[14.5px] font-medium text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
              >
                Downgrade to {planLabel(prevTier)}
              </button>
            )}

            {isPaidPlan && !isCanceled && nextTier && (
              <button
                type="button"
                onClick={() => setPendingChange(nextTier)}
                className="flex h-9 shrink-0 items-center rounded-full border border-border-strong bg-bg-panel px-4 text-[14.5px] font-medium text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
              >
                Upgrade to {planLabel(nextTier)}
              </button>
            )}

            {!isPaidPlan && showUpgrade && (
              <a
                href={routes.onboardingBilling}
                className="flex h-9 shrink-0 items-center rounded-full bg-accent px-4 text-[14.5px] font-semibold text-bg transition-colors hover:bg-accent/90"
              >
                Upgrade
              </a>
            )}
          </div>
        )}
      </div>

      <ColumnBar columns={COLUMNS} gap={18} divideTop={false} />

      {/* isPending, not isLoading. in query v5 `isLoading` is
          `isPending && isFetching`, so a query that is pending but not
          currently fetching — a paused retry, most obviously — reports
          isLoading false and isError false, and the list falls through to
          "No invoices yet". that false empty is the exact thing ErrorState
          was built to stop: it asserts you have none when the
          truth is we could not find out. */}
      {invoices.isPending ? (
        [0, 1, 2].map((i) => (
          <div
            key={i}
            className="flex h-16 items-center border-b border-border-subtle px-7"
          >
            <Skeleton className="h-4 w-full" />
          </div>
        ))
      ) : invoices.isError ? (
        <ErrorState
          title="Couldn't load invoices"
          description="Your plan and usage above are unaffected. This is the invoice history only."
          code={apiErrorCode(invoices.error)}
          onRetry={() => invoices.refetch()}
        />
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-1.5 py-24">
          <p className="text-[15px] text-text-secondary">No invoices yet</p>
          <p className="text-[14px] text-text-dim">
            The first one is issued at the end of your first paid period.
          </p>
        </div>
      ) : (
        rows.map((invoice) => (
          <DataRow key={invoice.id} height={64} gap={18}>
            <Cell>
              <span className="truncate text-[14.5px] text-text-primary">
                {formatDay(invoice.created_at)}
              </span>
            </Cell>

            <Cell width={120} align="right">
              <span className="text-[14px] tabular-nums text-text-secondary">
                {formatMoney(invoice.amount_paid, invoice.currency)}
              </span>
            </Cell>

            <Cell width={110}>
              <span className="inline-flex h-6 items-center rounded-xl border border-border-subtle bg-white/[0.03] px-2.5 text-[12.5px] text-text-dim">
                {invoice.status}
              </span>
            </Cell>

            <Cell width={110} align="right">
              {invoice.invoice_pdf && (
                <a
                  href={invoice.invoice_pdf}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[13.5px] text-text-dim transition-colors hover:text-text-primary"
                >
                  Download
                </a>
              )}
            </Cell>
          </DataRow>
        ))
      )}

      <ConfirmDialog
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        onConfirm={() =>
          cancelSubscription.mutate(undefined, {
            onSuccess: () => setCancelOpen(false),
          })
        }
        title="Cancel subscription"
        message={`You'll keep ${planDisplayName} features until the end of the current billing period, then drop to Free. Nothing is deleted.`}
        // the dialog's own dismiss button is hardcoded "Cancel", so a confirm
        // labelled "Cancel subscription" would put two Cancels side by side
        confirmLabel="Confirm cancellation"
        loading={cancelSubscription.isPending}
        loadingLabel="Canceling…"
      />

      {pendingChange && subscription && (
        <ChangePlanDialog
          currentTier={subscription.plan_tier}
          targetTier={pendingChange}
          onClose={() => setPendingChange(null)}
        />
      )}
    </div>
  );
}

// the proration preview is a *query*, so it renders its own inline isError —
// the global mutations.onError in query-provider does not cover queries.
function ChangePlanDialog({
  currentTier,
  targetTier,
  onClose,
}: {
  currentTier: PlanTier;
  targetTier: PlanTier;
  onClose: () => void;
}) {
  const preview = useSubscriptionChangePreview(targetTier);
  const changeSubscription = useChangeSubscription();

  const isUpgrade =
    SELF_SERVE_TIERS.indexOf(targetTier) > SELF_SERVE_TIERS.indexOf(currentTier);
  const proration = preview.data?.proration_amount ?? 0;

  return (
    <ConfirmDialog
      open
      onClose={onClose}
      onConfirm={() => changeSubscription.mutate(targetTier, { onSuccess: onClose })}
      // an upgrade or downgrade is consequential but not destructive
      tone="accent"
      title={`${isUpgrade ? "Upgrade" : "Downgrade"} to ${planLabel(targetTier)}?`}
      message="The change applies immediately. The difference is settled on your next invoice."
      confirmLabel={isUpgrade ? "Confirm upgrade" : "Confirm downgrade"}
      loading={changeSubscription.isPending}
      loadingLabel={isUpgrade ? "Upgrading…" : "Downgrading…"}
    >
      <div className="flex min-h-[64px] w-full flex-col gap-2 rounded-[10px] bg-bg-panel px-3.5 py-3">
        {preview.isLoading && (
          <div className="flex items-center gap-2 text-[13px] text-text-dim">
            <Loader2 size={13} className="animate-spin" />
            Calculating proration…
          </div>
        )}

        {preview.isError && (
          <p className="text-[13px] leading-[1.5] text-danger">
            Couldn&apos;t calculate the proration. You can still continue, or
            close and try again.
          </p>
        )}

        {preview.data && (
          <>
            <div className="flex items-center justify-between gap-4">
              <span className="text-[13px] text-text-dim">
                {proration >= 0
                  ? "Prorated charge on next invoice"
                  : "Prorated credit on next invoice"}
              </span>
              <span className="font-mono text-[13px] tabular-nums text-text-primary">
                {proration >= 0 ? "+" : "−"}
                {formatMoney(Math.abs(proration), preview.data.currency)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-[13px] text-text-dim">
                Next invoice total
              </span>
              <span className="font-mono text-[13px] tabular-nums text-text-primary">
                {formatMoney(
                  preview.data.next_invoice_total,
                  preview.data.currency,
                )}
              </span>
            </div>
          </>
        )}
      </div>
    </ConfirmDialog>
  );
}
