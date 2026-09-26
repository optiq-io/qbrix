"use client";

import { PoolsView } from "@/components/pools/pools-view";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes } from "@/config/routes";

export default function PoolsPage() {
  return (
    <GuardedRoute surface="pools" backHref={routes.home} backLabel="Back to home">
      <PoolsView />
    </GuardedRoute>
  );
}
