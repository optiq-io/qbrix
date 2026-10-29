"use client";

import { useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FrozenProvider, Offline } from "@qbrix/ui/next/offline";
import { auth } from "@/lib/api/auth";
import { useUnreachableSince } from "@/lib/api/reachability";

const RETRY_MS = 10_000;

/** freezes the page while qbrix isn't answering, asks again every 10 seconds, and
    refetches everything once it answers */
export function Reachability({ children }: { children: React.ReactNode }) {
  const since = useUnreachableSince();
  const queryClient = useQueryClient();

  const probe = useCallback(() => {
    auth.config().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!since) return;
    const timer = window.setInterval(probe, RETRY_MS);
    return () => {
      window.clearInterval(timer);
      queryClient.invalidateQueries();
    };
  }, [since, probe, queryClient]);

  return (
    <FrozenProvider since={since}>
      <Offline onRetry={probe} />
      {children}
    </FrozenProvider>
  );
}
