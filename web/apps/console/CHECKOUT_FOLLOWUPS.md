# Checkout Flow — Follow-up Items

Out-of-scope items from the initial checkout flow implementation that should be addressed in future iterations.

## 1. Merge login/register into email-first unified auth flow

Most modern SaaS apps (Stripe, Notion, Linear, Vercel) use a single auth page:
- User enters email
- If account exists → show password field
- If no account → show create account flow

This reduces friction significantly, especially in the checkout flow where you don't want users deciding between login vs register.

**Requires:** A new `POST /auth/check-email` endpoint in proxysvc to detect existing accounts, plus a full redesign of the auth pages.

## 2. Guard against already-subscribed users

If a user is already on the Pro plan and clicks "Upgrade to Pro" from the pricing page, Stripe handles proration — but the UX is confusing. The checkout page should detect the current subscription and show an appropriate message (e.g., "You're already on this plan").

**Requires:** Reading subscription status via `useSubscription` on the checkout page and conditionally rendering a different UI.

## 3. Update in-app "Upgrade Now" link in BillingTab

The `BillingTab` component's "Upgrade Now" button currently points to `/onboarding/billing`. For consistency, it should point to `/checkout?plan=pro` (or show a plan selector inline).

## 4. Centralize plan constants

Plan data (names, prices, features) is currently duplicated between:
- `apps/www/src/components/marketing/pricing-section.tsx` in the marketing site's repository
- `web/apps/console/src/components/onboarding/plan-selector.tsx`
- `web/apps/console/src/components/checkout/checkout-page-content.tsx`

The two console files should share one constants module; the marketing site keeps its own copy.

## 5. Store redirect intent server-side

Currently `return_to` is stored in localStorage. A more robust approach (used by most SaaS) is to store it in a session cookie or server-side session. This survives browser tab switches and incognito edge cases better.

## 6. Downgrade flow

Users clicking a lower-tier CTA from the pricing page (e.g., Pro user clicking Starter) should be handled gracefully — either blocked with a message or routed through a downgrade confirmation flow in settings.
