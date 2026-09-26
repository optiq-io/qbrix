import { apiFetch } from "@/lib/api/client";
import type {
  BillingSubscription,
  BillingInvoice,
  CheckoutSession,
  PortalSession,
  ChangePreview,
  PlanTier,
  UsageView,
} from "./types";

export const billing = {
  createCheckoutSession: async (
    priceId: string,
    successUrl: string,
    cancelUrl: string
  ): Promise<CheckoutSession> => {
    return apiFetch("/v1/ee/billing/checkout/session", {
      method: "POST",
      body: JSON.stringify({
        price_id: priceId,
        success_url: successUrl,
        cancel_url: cancelUrl,
      }),
    });
  },

  createPortalSession: async (returnUrl?: string): Promise<PortalSession> => {
    return apiFetch("/v1/ee/billing/portal/session", {
      method: "POST",
      body: JSON.stringify({ return_url: returnUrl }),
    });
  },

  getSubscription: async (): Promise<BillingSubscription> => {
    return apiFetch("/v1/ee/billing/subscription");
  },

  previewSubscriptionChange: async (
    targetTier: PlanTier
  ): Promise<ChangePreview> => {
    return apiFetch("/v1/ee/billing/subscription/change/preview", {
      method: "POST",
      body: JSON.stringify({ target_tier: targetTier }),
    });
  },

  changeSubscription: async (
    targetTier: PlanTier
  ): Promise<BillingSubscription> => {
    return apiFetch("/v1/ee/billing/subscription/change", {
      method: "POST",
      body: JSON.stringify({ target_tier: targetTier }),
    });
  },

  getUsage: async (): Promise<UsageView> => {
    return apiFetch("/v1/ee/billing/usage");
  },

  cancelSubscription: async (): Promise<void> => {
    return apiFetch("/v1/ee/billing/subscription/cancel", {
      method: "POST",
    });
  },

  reactivateSubscription: async (): Promise<void> => {
    return apiFetch("/v1/ee/billing/subscription/reactivate", {
      method: "POST",
    });
  },

  listInvoices: async (): Promise<{ invoices: BillingInvoice[] }> => {
    return apiFetch("/v1/ee/billing/invoices");
  },
};
