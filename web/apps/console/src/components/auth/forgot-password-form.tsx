"use client";

import Link from "next/link";
import { useState } from "react";
import { Mail, Loader2 } from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { auth } from "@/lib/api/auth";
import { resolveApiError } from "@/lib/api/handle-error";
import { Field, fieldInput } from "./field";
import { useRetryAfter } from "./use-retry-after";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  const limit = useRetryAfter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await auth.forgotPassword(email);
      setSubmitted(true);
    } catch (err: unknown) {
      if (limit.capture(err)) return;
      setError(resolveApiError(err, "something went wrong").message);
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <div className="flex flex-col">
        <h1 className="text-[36px] font-medium leading-[1.1] tracking-[-0.039em] text-text-primary">
          Check your email
        </h1>
        <p className="mt-2.5 text-[16px] leading-[1.5] text-text-dim">
          If an account exists for {email}, a reset link is on its way. It
          expires in 15 minutes.
        </p>
        <Link href="/login" className="mt-8">
          <Button variant="secondary" className="h-12 w-full text-[15.5px]">
            Back to sign in
          </Button>
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col">
      <h1 className="text-[36px] font-medium leading-[1.1] tracking-[-0.039em] text-text-primary">
        Reset password
      </h1>
      <p className="mt-2.5 text-[16px] leading-[1.5] text-text-dim">
        Enter your email and we&apos;ll send you a reset link.
      </p>

      {(limit.blocked || error) && (
        <div className="mt-8">
          <InlineBanner tone="danger" size="sm">
            {limit.blocked
              ? `Too many requests — try again in ${limit.remaining}s.`
              : error}
          </InlineBanner>
        </div>
      )}

      <div className="mt-8">
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
      </div>

      <Button
        type="submit"
        disabled={loading || limit.blocked}
        className="mt-5 h-[50px] w-full text-[15.5px]"
      >
        {loading && <Loader2 size={15} className="animate-spin" />}
        Send reset link
      </Button>

      <div className="mt-7 flex items-center gap-1.5">
        <span className="text-[13.5px] text-text-dim">
          Remember your password?
        </span>
        <Link
          href="/login"
          className="text-[13.5px] font-medium text-text-primary transition-opacity hover:opacity-70"
        >
          Sign in
        </Link>
      </div>
    </form>
  );
}
