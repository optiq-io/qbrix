"use client";

import { useSearchParams } from "next/navigation";
import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { Mail, Loader2, TriangleAlert, CircleCheck } from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { MonoLabel } from "@qbrix/ui/components/mono-label";
import { auth } from "@/lib/api/auth";
import { AuthShell } from "@/components/auth/auth-shell";
import { Field, fieldInput } from "@/components/auth/field";
import { TransactionalCard } from "@/components/auth/transactional-card";
import { useRetryAfter } from "@/components/auth/use-retry-after";
import { routes } from "@/config/routes";

type VerifyState = "verifying" | "success" | "invalid";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [state, setState] = useState<VerifyState>("verifying");

  // resend affordance (used on the invalid/expired state)
  const [email, setEmail] = useState("");
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);
  const limit = useRetryAfter();

  useEffect(() => {
    if (!token) {
      setState("invalid");
      return;
    }

    auth
      .verifyEmail(token)
      .then(() => setState("success"))
      .catch(() => setState("invalid"));
  }, [token]);

  async function handleResend(e: React.FormEvent) {
    e.preventDefault();
    setResending(true);
    try {
      await auth.resendVerification(email);
    } catch (err) {
      // enumeration-safe: always confirm, but a rate limit still has to show
      limit.capture(err);
    } finally {
      setResending(false);
      setResent(true);
    }
  }

  if (state === "verifying") {
    return (
      <div className="flex flex-col items-center gap-3 py-4">
        <Loader2 size={20} className="animate-spin text-text-dim" />
        <MonoLabel tone="dim">verifying your email…</MonoLabel>
      </div>
    );
  }

  // board `APP · Transactional states` / VERIFY → OK
  if (state === "success") {
    return (
      <TransactionalCard
        icon={CircleCheck}
        tone="positive"
        title="You're verified"
        body="Your workspace is ready. Pick a plan and you can run your first selection in about a minute."
      >
        <Link
          href={`${routes.onboardingBilling}?from=onboarding`}
          className="w-full"
        >
          <Button className="h-12 w-full text-[15.5px]">Choose a plan</Button>
        </Link>
        <Link href="/login?verified=true" className="w-full">
          <Button variant="secondary" className="h-12 w-full text-[15.5px]">
            Skip for now
          </Button>
        </Link>
      </TransactionalCard>
    );
  }

  // board `APP · Transactional states` / VERIFY → EXPIRED. the api cannot tell
  // an expired token from a bad or already-used one, so the copy covers all
  // three without claiming which it was.
  return (
    <TransactionalCard
      icon={TriangleAlert}
      tone="danger"
      title="This link has expired"
      body="Verification links last 24 hours. We can send a fresh one to the same address."
    >
      {limit.blocked && (
        <InlineBanner tone="danger" size="sm">
          Too many requests — try again in {limit.remaining}s.
        </InlineBanner>
      )}
      {resent && !limit.blocked ? (
        <InlineBanner tone="positive" size="sm">
          if an unverified account exists for that email, a new verification
          link has been sent.
        </InlineBanner>
      ) : (
        <form onSubmit={handleResend} className="flex flex-col gap-3 text-left">
          <Field label="Email" icon={Mail}>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className={fieldInput}
            />
          </Field>
          <Button
            type="submit"
            disabled={resending || limit.blocked}
            className="h-12 w-full text-[15.5px]"
          >
            {resending && <Loader2 size={15} className="animate-spin" />}
            Send a new link
          </Button>
        </form>
      )}
      <Link href="/login" className="w-full">
        <Button variant="secondary" className="h-12 w-full text-[15.5px]">
          Back to sign in
        </Button>
      </Link>
    </TransactionalCard>
  );
}

export default function VerifyEmailPage() {
  return (
    <AuthShell>
      <Suspense>
        <VerifyEmailContent />
      </Suspense>
    </AuthShell>
  );
}
