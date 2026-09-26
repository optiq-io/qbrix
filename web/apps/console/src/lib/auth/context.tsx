"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { auth } from "../api/auth";
import { purgeQueryCache } from "../query-provider";
import type { User } from "../api/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithApiKey: (apiKey: string) => Promise<void>;
  register: (name: string, email: string, password: string, workspaceName?: string, workspaceSlug?: string) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  updateUser: (user: User) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface AuthProviderProps {
  children: React.ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    auth
      .profile()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  // signing in also purges: an expired session leaves the tab on /login without
  // ever passing through logout, so this is the other door into the same tab.
  const login = useCallback(
    async (email: string, password: string) => {
      setLoading(true);
      try {
        purgeQueryCache();
        queryClient.clear();
        const result = await auth.login({ email, password });
        setUser(result.user);
      } finally {
        setLoading(false);
      }
    },
    [queryClient],
  );

  const loginWithApiKey = useCallback(
    async (apiKey: string) => {
      setLoading(true);
      try {
        purgeQueryCache();
        queryClient.clear();
        const result = await auth.login({ api_key: apiKey });
        setUser(result.user);
      } finally {
        setLoading(false);
      }
    },
    [queryClient],
  );

  const register = useCallback(async (name: string, email: string, password: string, workspaceName?: string, workspaceSlug?: string) => {
    setLoading(true);
    try {
      return await auth.register({
        name,
        email,
        password,
        workspace_name: workspaceName,
        workspace_slug: workspaceSlug,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    await auth.logout();
    setUser(null);
    // the query cache is persisted to sessionStorage, so the tab outlives the
    // session unless both copies go. signing in as someone else in the same tab
    // would otherwise open on the previous workspace's experiments.
    purgeQueryCache();
    queryClient.clear();
  }, [queryClient]);

  const refresh = useCallback(async () => {
    try {
      const profile = await auth.profile();
      setUser(profile);
    } catch {
      setUser(null);
    }
  }, []);

  const updateUser = useCallback((updatedUser: User) => {
    setUser(updatedUser);
  }, []);

  const value: AuthContextValue = {
    user,
    loading,
    login,
    loginWithApiKey,
    register,
    logout,
    refresh,
    updateUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}