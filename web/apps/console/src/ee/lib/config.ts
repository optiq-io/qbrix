"use client";

import { useQuery } from "@tanstack/react-query";

export interface RuntimeConfig {
  stripePriceIdStarter: string;
  stripePriceIdGrowth: string;
  stripePriceIdScale: string;
}

export function useRuntimeConfig() {
  return useQuery<RuntimeConfig>({
    queryKey: ["runtime-config"],
    queryFn: async () => {
      const res = await fetch("/internal/config");
      if (!res.ok) throw new Error("failed to load runtime config");
      return res.json();
    },
    staleTime: Infinity,
    gcTime: Infinity,
  });
}