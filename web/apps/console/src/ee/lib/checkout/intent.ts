import { routes } from "@/config/routes";

const CHECKOUT_INTENT_KEY = "qbrix.checkout_intent";

type CheckoutPlan = "starter" | "growth" | "scale";

export function setCheckoutIntent(plan: CheckoutPlan): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(CHECKOUT_INTENT_KEY, plan);
}

export function getCheckoutIntent(): CheckoutPlan | null {
  if (typeof window === "undefined") return null;
  const value = localStorage.getItem(CHECKOUT_INTENT_KEY);
  if (value === "starter" || value === "growth" || value === "scale") return value;
  return null;
}

export function clearCheckoutIntent(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(CHECKOUT_INTENT_KEY);
}

// the post-login destination, consumed once. core calls this without knowing
// what a checkout is; in oss no intent is ever written, so it yields null.
export function takeCheckoutRedirect(): string | null {
  const plan = getCheckoutIntent();
  if (!plan) return null;
  clearCheckoutIntent();
  return routes.checkout(plan);
}
