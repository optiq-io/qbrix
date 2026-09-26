"use client";

import { PoolsView } from "@/components/pools/pools-view";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes } from "@/config/routes";

// the same view as `/pools`, opened with its draft row. a route rather than a
// query flag so the palette, a link and a bookmark all reach it the same way —
// and so cancelling is a navigation back to `/pools`, not hidden state.

export default function NewPoolPage() {
  return (
    <GuardedRoute surface="pools" backHref={routes.home} backLabel="Back to home">
      <PoolsView draftOpen />
    </GuardedRoute>
  );
}
