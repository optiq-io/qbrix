"use client";

import Link from "next/link";
import { useState } from "react";
import { Lock, EyeOff, Eye, Loader2, CircleCheck, TriangleAlert } from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { auth } from "@/lib/api/auth";
import { resolveApiError } from "@/lib/api/handle-error";
import { Field, fieldInput } from "./field";
import { TransactionalCard } from "./transactional-card";
import { useRetryAfter } from "./use-retry-after";

interface ResetPasswordFormProps {
  token: string | null;
}

export function ResetPasswordForm({ token }: ResetPasswordFormProps) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const limit = useRetryAfter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (newPassword !== confirmPassword) {
      setError("passwords do not match");
      return;
    }

    setLoading(true);
    try {
      await auth.resetPassword(token!, newPassword);
      setSuccess(true);
    } catch (err: unknown) {
      if (limit.capture(err)) return;
      setError(resolveApiError(err, "failed to reset password").message);
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <TransactionalCard
        icon={TriangleAlert}
        tone="danger"
        title="Invalid link"
        body="This reset link is missing its token. Request a new one and we'll send a fresh link to the same address."
      >
        <Link href="/forgot-password" className="w-full">
          <Button className="h-12 w-full text-[15.5px]">
            Request a new link
          </Button>
        </Link>
        <Link href="/login" className="w-full">
          <Button variant="secondary" className="h-12 w-full text-[15.5px]">
            Back to sign in
          </Button>
        </Link>
      </TransactionalCard>
    );
  }

  if (success) {
    return (
      <TransactionalCard
        icon={CircleCheck}
        tone="positive"
        title="Password updated"
        body="Your password has been reset. You can sign in with it now."
      >
        <Link href="/login" className="w-full">
          <Button className="h-12 w-full text-[15.5px]">Sign in</Button>
        </Link>
      </TransactionalCard>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col">
      <h1 className="text-[36px] font-medium leading-[1.1] tracking-[-0.039em] text-text-primary">
        Set a new password
      </h1>
      <p className="mt-2.5 text-[16px] leading-[1.5] text-text-dim">
        Choose something you don&apos;t use anywhere else.
      </p>

      {(limit.blocked || error) && (
        <div className="mt-8">
          <InlineBanner tone="danger" size="sm">
            {limit.blocked
              ? `Too many attempts — try again in ${limit.remaining}s.`
              : error}
          </InlineBanner>
        </div>
      )}

      <div className="mt-8 flex flex-col gap-[18px]">
        <Field label="New password" icon={Lock}>
          <input
            type={showNew ? "text" : "password"}
            required
            minLength={8}
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="min 8 characters"
            className={fieldInput}
          />
          <button
            type="button"
            onClick={() => setShowNew(!showNew)}
            aria-label={showNew ? "Hide password" : "Show password"}
            className="text-text-faint transition-colors hover:text-text-secondary"
          >
            {showNew ? <Eye size={15} /> : <EyeOff size={15} />}
          </button>
        </Field>

        <Field label="Confirm password" icon={Lock}>
          <input
            type={showConfirm ? "text" : "password"}
            required
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="repeat it"
            className={fieldInput}
          />
          <button
            type="button"
            onClick={() => setShowConfirm(!showConfirm)}
            aria-label={showConfirm ? "Hide password" : "Show password"}
            className="text-text-faint transition-colors hover:text-text-secondary"
          >
            {showConfirm ? <Eye size={15} /> : <EyeOff size={15} />}
          </button>
        </Field>
      </div>

      <Button
        type="submit"
        disabled={loading || limit.blocked}
        className="mt-5 h-[50px] w-full text-[15.5px]"
      >
        {loading && <Loader2 size={15} className="animate-spin" />}
        Reset password
      </Button>
    </form>
  );
}
