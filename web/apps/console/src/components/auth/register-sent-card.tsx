"use client";

import Link from "next/link";
import { useState } from "react";
import { Loader2, MailCheck } from "lucide-react";
import { Button } from "@qbrix/ui/components/button";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { TransactionalCard } from "./transactional-card";
import { useRetryAfter } from "./use-retry-after";

// board `APP · Transactional states` / REGISTER → SENT
export function RegisterSentCard({
  email,
  onResend,
}: {
  email: string;
  onResend: (email: string) => Promise<unknown>;
}) {
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);
  const limit = useRetryAfter();

  async function handleResend() {
    setResending(true);
    try {
      await onResend(email);
    } catch (err) {
      // enumeration-safe: always confirm, but a rate limit still has to show
      limit.capture(err);
    } finally {
      setResending(false);
      setResent(true);
    }
  }

  return (
    <TransactionalCard
      icon={MailCheck}
      title="Check your email"
      body={
        <>
          We sent a verification link to{" "}
          <span className="text-text-secondary">{email}</span>. It expires in 24
          hours.
        </>
      }
    >
      {limit.blocked && (
        <InlineBanner tone="danger" size="sm">
          Too many requests — try again in {limit.remaining}s.
        </InlineBanner>
      )}
      {resent && !limit.blocked && (
        <InlineBanner tone="positive" size="sm">
          verification link sent — check your inbox.
        </InlineBanner>
      )}
      <Button
        onClick={handleResend}
        disabled={resending || limit.blocked}
        className="h-12 w-full text-[15.5px]"
      >
        {resending && <Loader2 size={15} className="animate-spin" />}
        Resend email
      </Button>
      <Link href="/login" className="w-full">
        <Button variant="secondary" className="h-12 w-full text-[15.5px]">
          Back to sign in
        </Button>
      </Link>
    </TransactionalCard>
  );
}
