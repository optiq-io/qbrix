"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { auth } from "@/lib/api/auth";
import { connections } from "@/lib/api/connections";
import { queryKeys } from "@/lib/api/query-keys";
import { runtime } from "@/lib/api/runtime";
import { useAuth } from "@/lib/auth/context";
import { yours } from "@/lib/connection/health";

export function useMinute(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

export function useWorkspace() {
  const { user } = useAuth();
  return useQuery({
    queryKey: queryKeys.workspace.current,
    queryFn: () => auth.getWorkspace(),
    enabled: !!user,
    staleTime: 5 * 60_000,
  });
}

export function useWorkspaceStatus() {
  const { user } = useAuth();
  return useQuery({
    queryKey: queryKeys.runtime.status,
    queryFn: runtime.status,
    enabled: !!user,
    refetchInterval: 30_000,
  });
}

export function useYourConnections() {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: queryKeys.connections.list,
    queryFn: connections.list,
    enabled: !!user,
    staleTime: 60_000,
  });
  return { ...query, data: query.data ? yours(query.data, user?.id) : undefined };
}
