"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth/context";
import { useEntitlements } from "@/lib/entitlements";
import { billing } from "./api";
import { METERED_TIERS } from "./types";
import type {
  BillingSubscription,
  BillingInvoice,
  SelectionUsage,
  UsageView,
  PlanTier,
} from "./types";

const QUERY_KEYS = {
  subscription: ["billing", "subscription"] as const,
  invoices: ["billing", "invoices"] as const,
  usage: ["billing", "usage"] as const,
  changePreview: ["billing", "change-preview"] as const,
};

export function useSubscription() {
  return useQuery<BillingSubscription>({
    queryKey: QUERY_KEYS.subscription,
    queryFn: billing.getSubscription,
    staleTime: 1000 * 60, // 1 minute
  });
}

// not exported: this endpoint 404s for free and enterprise, so a surface
// calling it directly would render nothing for them and look correct doing it.
// useSelectionUsage below is the only supported way in.
function useUsage({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<UsageView>({
    queryKey: QUERY_KEYS.usage,
    queryFn: billing.getUsage,
    staleTime: 1000 * 60, // 1 minute
    retry: false,
    enabled,
  });
}

// the meter's numerator differs by tier, because the number with a consequence
// differs by tier: a free tenant is cut off by the proxy's own selection
// counter, a paid tenant is invoiced from stripe. the counter is approximate
// and explicitly never bills, so it must not be rendered next to money; stripe
// 404s without a metered subscription, so it cannot serve free. resolved here
// once rather than at each surface.
export function useSelectionUsage(): {
  data: SelectionUsage | null;
  isLoading: boolean;
} {
  const { user } = useAuth();
  const { isCloud } = useEntitlements();

  const plan_tier = user?.plan_tier;
  const metered = !!plan_tier && METERED_TIERS.includes(plan_tier);
  const { data: billed, isLoading } = useUsage({
    enabled: isCloud && metered,
  });

  if (!isCloud || !plan_tier) return { data: null, isLoading: false };

  if (metered) {
    if (!billed) return { data: null, isLoading };
    return {
      data: {
        used: billed.used,
        included: billed.included,
        overage: billed.overage,
        overageCost: billed.overage_cost,
        currency: billed.currency,
        periodStart: parseDate(billed.period_start),
        periodEnd: parseDate(billed.period_end),
        capped: false,
      },
      isLoading: false,
    };
  }

  const usage = user?.usage;
  if (usage?.selections_this_period === undefined) {
    return { data: null, isLoading: false };
  }
  const limit = user?.limits?.included_selections_per_month;
  const included = limit === undefined || limit === -1 ? null : limit;

  return {
    data: {
      used: usage.selections_this_period,
      included,
      overage: null,
      overageCost: null,
      currency: null,
      periodStart: parseDate(usage.period_start),
      periodEnd: parseDate(usage.period_end),
      capped: included !== null && usage.selections_this_period >= included,
    },
    isLoading: false,
  };
}

// stripe sends the period as an iso string, the profile as epoch seconds
function parseDate(value: string | number | undefined | null): Date | null {
  if (value === undefined || value === null) return null;
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function useInvoices() {
  return useQuery<{ invoices: BillingInvoice[] }>({
    queryKey: QUERY_KEYS.invoices,
    queryFn: billing.listInvoices,
  });
}

export function useCreateCheckoutSession() {
  return useMutation({
    mutationFn: ({
      priceId,
      successUrl,
      cancelUrl,
    }: {
      priceId: string;
      successUrl: string;
      cancelUrl: string;
    }) => billing.createCheckoutSession(priceId, successUrl, cancelUrl),
    onSuccess: (data) => {
      // Redirect to Stripe Checkout
      window.location.href = data.url;
    },
  });
}

export function useCreatePortalSession() {
  return useMutation({
    mutationFn: (returnUrl?: string) => billing.createPortalSession(returnUrl),
    onSuccess: (data) => {
      window.location.href = data.url;
    },
  });
}

export function useSubscriptionChangePreview(targetTier: PlanTier | null) {
  return useQuery({
    queryKey: [...QUERY_KEYS.changePreview, targetTier],
    queryFn: () => billing.previewSubscriptionChange(targetTier as PlanTier),
    enabled: !!targetTier,
    staleTime: 0,
    retry: false,
  });
}

export function useChangeSubscription() {
  const queryClient = useQueryClient();
  const { refresh } = useAuth();

  return useMutation({
    mutationFn: (targetTier: PlanTier) => billing.changeSubscription(targetTier),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.subscription });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.invoices });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.usage });
      // entitlements ride on the profile, not on the subscription — without
      // this, the gates keep answering on the old tier until a full reload
      await refresh();
    },
  });
}

export function useCancelSubscription() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: billing.cancelSubscription,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.subscription });
    },
  });
}

export function useReactivateSubscription() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: billing.reactivateSubscription,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.subscription });
    },
  });
}
