"use client";

import { useQuery } from "@tanstack/react-query";
import { auth } from "@/lib/api/auth";
import { queryKeys } from "@/lib/api/query-keys";
import type { Edition } from "@/lib/api/types";

// what the console can know about the deployment before anyone signs in.
//
// `lib/entitlements.ts` answers the same kind of question from the profile,
// but the auth screens run without one: a self-hosted instance has to be able
// to say "registration is closed" and to stop advertising qbrix cloud's plans
// and legal terms as if they were its own.

type Deployment = {
  /** null until the config lands, so a surface can render nothing rather than guess */
  edition: Edition | null;
  isCloud: boolean;
  /** public registration is accepted right now */
  signupOpen: boolean;
  /** a mail provider is configured; without one, accounts are auto-verified */
  emailEnabled: boolean;
  isLoading: boolean;
};

export function useDeployment(): Deployment {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.deployment.config,
    queryFn: auth.config,
    // not Infinity: in first-user mode signup closes the moment somebody
    // registers, and the cache is restored from sessionStorage across reloads
    staleTime: 30_000,
    retry: false,
  });

  return {
    edition: data?.edition ?? null,
    isCloud: data?.edition === "cloud",
    // open until told otherwise: the register form must not flash a closed
    // state on a healthy cloud while the config is in flight
    signupOpen: data?.signup_open ?? true,
    emailEnabled: data?.email_enabled ?? true,
    isLoading,
  };
}
