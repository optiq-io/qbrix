"use client";

import { AuthShell } from "@/components/auth/auth-shell";
import { RegisterForm } from "@/components/auth/register-form";
import { useDeployment } from "@/lib/deployment";
import { ShowcaseFreeTier } from "@/lib/edition";

export default function RegisterPage() {
  // the free tier is qbrix cloud's plan; self-host has nothing to show beside
  // the form, and an empty showcase column is worse than none — so the
  // decision is made here, where the layout is chosen.
  const { isCloud } = useDeployment();

  return (
    <AuthShell showcase={isCloud ? <ShowcaseFreeTier /> : undefined}>
      <RegisterForm />
    </AuthShell>
  );
}
