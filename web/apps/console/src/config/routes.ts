export const routes = {
  marketing: "/",

  // app shell
  home: "/",
  pools: "/pools",
  eventLog: "/developers/event-log",
  settings: "/settings",
  settingsApiKeys: "/settings?tab=api-keys",
  // the plan comparison surface (plan-selector.tsx). named for onboarding but
  // it is the only "compare the tiers" page the console has — the gated
  // UpgradeCard sends people here.
  onboardingBilling: "/onboarding/billing",
  settingsUsers: "/settings?tab=members",
  settingsBilling: "/settings?tab=billing",

  // creation flows — real routes, so the palette, a link and a bookmark all
  // reach them the same way. `?pool=` prefills the picker.
  newExperiment: (poolId?: string) =>
    poolId ? `/experiments/new?pool=${poolId}` : "/experiments/new",
  newPool: "/pools/new",

  // experiment workspace tabs
  experimentOverview: (id: string) => `/experiments/${id}`,
  experimentArms: (id: string) => `/experiments/${id}/arms`,
  experimentPolicy: (id: string) => `/experiments/${id}/policy`,
  experimentGate: (id: string) => `/experiments/${id}/gate`,
  experimentActivity: (id: string) => `/experiments/${id}/activity`,
  experimentInsights: (id: string) => `/experiments/${id}/insights`,

  // legacy aliases (kept for any lingering callers; resolve to new routes)
  dashboard: "/",
  experiments: "/",
  experimentDetail: (id: string) => `/experiments/${id}`,

  // auth + commerce
  login: "/login",
  register: "/register",
  checkout: (plan?: string) => (plan ? `/checkout?plan=${plan}` : "/checkout"),

  // marketing sub-routes (link-out targets)
  architecture: "/architecture",
  pricing: "/pricing",
  docs: "/docs",
} as const;

// docs live on the marketing site, so a console link-out has to be absolute —
// `/docs/…` resolves against cloud.qbrix.io and 404s. the host is hardcoded for
// the same reason `(auth)/layout.tsx` hardcodes it: there is one marketing
// origin and it is not deployment-dependent.
//
// slugs are the filenames in /docs at the repo root. only link to one that
// exists — a dead link on an empty state is worse than no link at all.
export function docsUrl(slug: string): string {
  return `https://qbrix.io/docs/${slug}`;
}
