"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "./context";
import { AppShellSkeleton } from "@/components/shell/shell-skeleton";

interface AuthGuardProps {
  children: React.ReactNode;
  requireAuth?: boolean;
}

export function AuthGuard({ children, requireAuth = true }: AuthGuardProps) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && requireAuth && !user) {
      const currentPath = window.location.pathname + window.location.search;
      router.replace(`/login?redirect=${encodeURIComponent(currentPath)}`);
    }
  }, [user, loading, requireAuth, router]);

  if (loading) {
    return <AppShellSkeleton />;
  }

  if (requireAuth && !user) {
    return null;
  }

  return <>{children}</>;
}