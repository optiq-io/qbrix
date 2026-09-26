"use client";

// the one module outside `src/ee` and `src/app/(ee)` allowed to import from
// them. every cloud-only surface a core screen renders arrives through here, so
// moving `src/ee` behind a different edition — or out of this repo — is a change
// to this file and nothing else.
//
// `scripts/check-edition-boundary.mjs` fails the build when anything else
// reaches across.
//
// the gate vocabulary is *not* here: `lib/entitlements.ts` owns it, because
// `src/ee` reads it too and this file must not be part of a cycle.

export { FeatureGate } from "@/ee/components/feature-gate";
export { BillingTab } from "@/ee/components/settings/billing-tab";
export { RoleUpgradeNote } from "@/ee/components/settings/role-upgrade-note";
export { PlanLine } from "@/ee/components/shell/plan-line";
export { planLabel } from "@/ee/lib/billing/plans";
export { takeCheckoutRedirect } from "@/ee/lib/checkout/intent";

// pre-auth, so its gate is `lib/deployment.ts` (GET /auth/config) rather than
// the profile's entitlements.
export { ShowcaseFreeTier } from "@/ee/components/auth/showcase-free-tier";
